import { vi } from "vitest";

export interface MockRoute {
  once?: boolean;
  match: (request: Request, url: URL) => boolean;
  handle: (request: Request, url: URL) => Response | Promise<Response>;
}

export interface CapturedRequest {
  bodyText: string;
  method: string;
  url: string;
}

export function route(
  method: string,
  pathname: string,
  handle: MockRoute["handle"],
  options: { once?: boolean } = {}
): MockRoute {
  return {
    once: options.once ?? false,
    match: (request, url) =>
      request.method.toUpperCase() === method.toUpperCase() &&
      url.pathname === pathname,
    handle,
  };
}

export function jsonResponse(
  body: unknown,
  init: ResponseInit = {}
): Response {
  return Response.json(body, init);
}

export function textResponse(
  body: string,
  init: ResponseInit = {}
): Response {
  return new Response(body, init);
}

export function sseResponse(
  payloads: Array<object | string>,
  options: { chunkSize?: number } = {}
): Response {
  const rawBody = payloads
    .map((payload) =>
      typeof payload === "string"
        ? payload
        : `data: ${JSON.stringify(payload)}\n\n`
    )
    .join("");
  const chunkSize = Math.max(1, options.chunkSize ?? (rawBody.length || 1));
  const encoder = new TextEncoder();

  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let index = 0; index < rawBody.length; index += chunkSize) {
        controller.enqueue(encoder.encode(rawBody.slice(index, index + chunkSize)));
      }
      controller.close();
    },
  });

  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream",
    },
    status: 200,
  });
}

export function installMockFetch(routes: MockRoute[]) {
  const activeRoutes = [...routes];
  const captured: CapturedRequest[] = [];

  const fetchSpy = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const request = new Request(input, init);
      const url = new URL(request.url);
      const bodyText =
        request.method === "GET" || request.method === "HEAD"
          ? ""
          : await request.clone().text();

      captured.push({
        bodyText,
        method: request.method,
        url: url.toString(),
      });

      const routeIndex = activeRoutes.findIndex((candidate) =>
        candidate.match(request, url)
      );

      if (routeIndex < 0) {
        throw new Error(`Unhandled fetch: ${request.method} ${url.pathname}${url.search}`);
      }

      const matchedRoute = activeRoutes[routeIndex];
      if (matchedRoute.once) {
        activeRoutes.splice(routeIndex, 1);
      }

      return matchedRoute.handle(request, url);
    });

  return {
    captured,
    pendingRoutes: () => [...activeRoutes],
    restore: () => fetchSpy.mockRestore(),
  };
}
