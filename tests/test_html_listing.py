import unittest

from src.parsers import html_listing


class HtmlListingParserTests(unittest.TestCase):
    def test_configured_listing_fields_are_normalized(self):
        html = """
        <div class="card" data-item="abc-7">
          <a class="title" href="/item/abc-7"><span>Example Item</span></a>
          <img class="photo" data-src="/images/item.jpg">
          <span class="old">₹12,000</span>
          <span class="new">₹9,500</span>
          <span class="stock">In Stock</span>
        </div>
        """
        config = {
            "card_selector": ".card",
            "id_attribute": "data-item",
            "title_selectors": [".title"],
            "url_selectors": [".title"],
            "image_selectors": [".photo"],
            "image_attributes": ["data-src"],
            "regular_price_selectors": [".old"],
            "sale_price_selectors": [".new"],
            "stock_selectors": [".stock"],
            "showing_regex": r"Showing (\d+) to (\d+) of (\d+) \((\d+) Pages\)",
        }
        items, meta = html_listing.parse_listing_html(
            html, "https://example.invalid/search?page=1", config
        )
        self.assertEqual(meta["cards_found"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0],
            {
                "merchant_item_id": "abc-7",
                "product_url": "https://example.invalid/item/abc-7",
                "image_url": "https://example.invalid/images/item.jpg",
                "title": "Example Item",
                "product_type": None,
                "brand": None,
                "mpn": None,
                "gtin": None,
                "ean": None,
                "upc": None,
                "feed_condition": "new",
                "availability": "in_stock",
                "price": 12000.0,
                "sale_price": 9500.0,
                "effective_price": 9500.0,
                "raw_payload": {
                    "source": "html_listing",
                    "page_url": "https://example.invalid/search?page=1",
                    "price_regular": 12000.0,
                    "price_sale": 9500.0,
                },
            },
        )

    def test_pdp_json_ld_and_soft_delete(self):
        product = """
        <html><head>
          <script type="application/ld+json">
          {"@type":"Product","name":"Example CPU","brand":{"name":"Example Brand"},
           "model":"EX-1","offers":{"price":"1234","availability":"https://schema.org/InStock"}}
          </script>
        </head><body><h1>Example CPU</h1></body></html>
        """
        parsed = html_listing.parse_pdp_html(
            product,
            requested_url="https://example.invalid/item/ex-1",
            final_url="https://example.invalid/item/ex-1",
        )
        self.assertEqual(parsed["title"], "Example CPU")
        self.assertEqual(parsed["brand"], "Example Brand")
        self.assertEqual(parsed["mpn"], "EX-1")
        self.assertEqual(parsed["effective_price"], 1234.0)
        self.assertEqual(parsed["availability"], "in_stock")

        deleted = html_listing.parse_pdp_html(
            "<html><body><h1>Home</h1></body></html>",
            requested_url="https://example.invalid/item/ex-1",
            final_url="https://example.invalid/",
        )
        self.assertTrue(deleted["raw_payload"]["soft_deleted"])
        self.assertEqual(deleted["availability"], "out_of_stock")


if __name__ == "__main__":
    unittest.main()
