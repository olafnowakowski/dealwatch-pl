# Use HTTP with x-kom's server-rendered hydration payload

## Context

The first DealWatch PL retailer is x-kom's graphics-card category. The MVP needs a
reliable, low-overhead way to collect current product offers.

## Decision

Fetch the public category pages over ordinary HTTP, request 60 products per page,
follow the document's `rel="next"` link, and parse the JSON assigned to
`window.__INITIAL_STATE__['app']`. The collector does not execute JavaScript or use
an undocumented internal endpoint.

## Consequences

This keeps the runtime to HTTP plus the Python standard library and provides the
listing fields required by the MVP. The payload is an implementation detail of the
web page, so fixture tests guard the parser and future x-kom markup changes require
adapter maintenance. Browser automation and external scraping services remain
fallbacks only if this method stops working.
