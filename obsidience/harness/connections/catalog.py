"""Display-only descriptions and presets for the supported connection adapters."""

PROVIDERS = [{
    "id": "bbc", "name": "BBC News", "kind": "rss",
    "url": "https://feeds.bbci.co.uk/news/rss.xml",
    "description": "BBC News RSS entries provide headlines, publication dates, reporting links and publisher-supplied descriptions.",
    "feeds": [
        {"name": "Top stories", "url": "https://feeds.bbci.co.uk/news/rss.xml",
         "description": "BBC's top-story feed supplies selected news headlines and descriptions. Included text varies by item."},
        {"name": "World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
         "description": "BBC's World feed supplies international news headlines and descriptions. Included text varies by item."},
    ],
}]
