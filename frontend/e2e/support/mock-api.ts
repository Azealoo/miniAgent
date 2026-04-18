import type { Page, Route } from "@playwright/test";

export interface BrowserCapturedRequest {
  bodyText: string;
  method: string;
  url: string;
}

export interface BrowserMockRoute {
  once?: boolean;
  match: (method: string, url: URL) => boolean;
  handle: (route: Route, url: URL) => Promise<void> | void;
}

const API_ORIGIN = "http://127.0.0.1:8002";

function corsHeaders(
  headers: Record<string, string> = {}
): Record<string, string> {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
    ...headers,
  };
}

export function route(
  method: string,
  pathname: string,
  handle: BrowserMockRoute["handle"],
  options: { once?: boolean } = {}
): BrowserMockRoute {
  return {
    once: options.once ?? false,
    match: (candidateMethod, url) =>
      candidateMethod.toUpperCase() === method.toUpperCase() &&
      url.pathname === pathname,
    handle,
  };
}

export async function fulfillJson(
  route: Route,
  body: unknown,
  init: { headers?: Record<string, string>; status?: number } = {}
) {
  await route.fulfill({
    body: JSON.stringify(body),
    headers: corsHeaders({
      "content-type": "application/json; charset=utf-8",
      ...init.headers,
    }),
    status: init.status ?? 200,
  });
}

export async function fulfillText(
  route: Route,
  body: string,
  init: { contentType?: string; headers?: Record<string, string>; status?: number } = {}
) {
  await route.fulfill({
    body,
    headers: corsHeaders({
      "content-type": init.contentType ?? "text/plain; charset=utf-8",
      ...init.headers,
    }),
    status: init.status ?? 200,
  });
}

export async function fulfillSse(
  route: Route,
  payloads: Array<object | string>,
  init: { headers?: Record<string, string>; status?: number } = {}
) {
  const body = payloads
    .map((payload) =>
      typeof payload === "string"
        ? payload
        : `data: ${JSON.stringify(payload)}\n\n`
    )
    .join("");

  await route.fulfill({
    body,
    headers: corsHeaders({
      "cache-control": "no-cache",
      "content-type": "text/event-stream; charset=utf-8",
      ...init.headers,
    }),
    status: init.status ?? 200,
  });
}

export async function installApiMock(page: Page, routes: BrowserMockRoute[]) {
  const activeRoutes = [...routes];
  const captured: BrowserCapturedRequest[] = [];

  await page.route(`${API_ORIGIN}/api/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();

    if (method === "OPTIONS") {
      await route.fulfill({
        body: "",
        headers: corsHeaders(),
        status: 204,
      });
      return;
    }

    captured.push({
      bodyText:
        method === "GET" || method === "HEAD" ? "" : (request.postData() ?? ""),
      method,
      url: url.toString(),
    });

    const routeIndex = activeRoutes.findIndex((candidate) =>
      candidate.match(method, url)
    );
    if (routeIndex < 0) {
      throw new Error(`Unhandled browser API route: ${method} ${url.pathname}${url.search}`);
    }

    const matched = activeRoutes[routeIndex];
    if (matched.once) {
      activeRoutes.splice(routeIndex, 1);
    }

    await matched.handle(route, url);
  });

  return {
    captured,
    pendingRoutes: () => [...activeRoutes],
  };
}
