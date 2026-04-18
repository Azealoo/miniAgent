# Knowledge cache

This directory stores cached content from online lookups (e.g. PubMed, UniProt) when using the **cache_to_knowledge** skill. Files are organized as:

- `cache/pubmed/<PMID>.md`
- `cache/uniprot/<id>.md`
- etc.

They are indexed by `search_knowledge_base` so you can retrieve them later. Do not edit these by hand unless needed; the agent writes here.
