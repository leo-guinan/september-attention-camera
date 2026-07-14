# Receipt schema

Current receipt schema: `attention-sensor-v1`.

```json
{
  "schema_version": "attention-sensor-v1",
  "captured_at": "2026-07-14T19:30:00Z",
  "page_url": "https://x.com/DefenderOfBasic",
  "page_title": "...",
  "capture_mode": "page_load | mutation | spa_navigation | manual",
  "target": {
    "id": "psyop",
    "name": "Psyop Report",
    "surface": "x_profile",
    "handle": "DefenderOfBasic"
  },
  "visible_stats": {
    "followers": 1234,
    "following": 88,
    "subscribers": null,
    "posts": null,
    "likes": 560,
    "reposts": 34,
    "replies": 12,
    "views": 9876,
    "publicNumbers": []
  },
  "derived": {
    "audience": 1234,
    "interactions": 606,
    "exposure": 9876,
    "attention": 785,
    "trustBasis": "visible_audience_and_interactions"
  },
  "coverage": {
    "visible_dom_only": true,
    "hidden_replies_missing": true,
    "private_analytics_missing": true,
    "authenticated_platform_api_not_used": true
  }
}
```
