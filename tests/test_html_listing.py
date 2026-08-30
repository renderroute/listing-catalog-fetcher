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
           "model":"EX-1","gtin13":"1234567890123",
           "offers":{"price":"1234","availability":"https://schema.org/InStock"}}
          </script>
        </head><body>
          <h1>Example CPU</h1>
          <div>UPC: 012345678905</div>
        </body></html>
        """
        parsed = html_listing.parse_pdp_html(
            product,
            requested_url="https://example.invalid/item/ex-1",
            final_url="https://example.invalid/item/ex-1",
        )
        self.assertEqual(parsed["title"], "Example CPU")
        self.assertEqual(parsed["brand"], "Example Brand")
        self.assertEqual(parsed["mpn"], "EX-1")
        self.assertEqual(parsed["ean"], "1234567890123")
        self.assertEqual(parsed["upc"], "012345678905")
        self.assertEqual(parsed["effective_price"], 1234.0)
        self.assertEqual(parsed["availability"], "in_stock")

        deleted = html_listing.parse_pdp_html(
            "<html><body><h1>Home</h1></body></html>",
            requested_url="https://example.invalid/item/ex-1",
            final_url="https://example.invalid/",
        )
        self.assertTrue(deleted["raw_payload"]["soft_deleted"])
        self.assertEqual(deleted["availability"], "out_of_stock")

    def test_pdp_visible_vedant_labels(self):
        product = """
        <html><body>
          <h1>Example GPU</h1>
          <div>Stock: In Stock</div>
          <div>Brand: Gigabyte</div>
          <div>Model: GV-EXAMPLE-1</div>
          <div>UPC: 889523047521</div>
          <div>EAN: 4719331355494</div>
        </body></html>
        """
        parsed = html_listing.parse_pdp_html(
            product,
            requested_url="https://example.invalid/item/example",
            final_url="https://example.invalid/item/example",
            config={"product_markers": ["h1"]},
        )
        self.assertEqual(parsed["brand"], "Gigabyte")
        self.assertEqual(parsed["mpn"], "GV-EXAMPLE-1")
        self.assertEqual(parsed["upc"], "889523047521")
        self.assertEqual(parsed["ean"], "4719331355494")

    def test_pdp_visible_md_labels(self):
        product = """
        <html><body>
          <h1>Gigabyte RTX 5080 Gaming OC 16GB GDDR7 Graphics Card</h1>
          <ul class="product-details">
            <li>Brand: GIGABYTE</li>
            <li>Product Code: GV-N5080GAMING-OC-16GD</li>
            <li>Availability: In Stock</li>
          </ul>
        </body></html>
        """
        parsed = html_listing.parse_pdp_html(
            product,
            requested_url="https://example.invalid/product/example",
            final_url="https://example.invalid/product/example",
            config={"product_markers": [".product-details"]},
        )
        self.assertEqual(parsed["brand"], "GIGABYTE")
        self.assertEqual(parsed["mpn"], "GV-N5080GAMING-OC-16GD")
        self.assertEqual(parsed["availability"], "in_stock")


if __name__ == "__main__":
    unittest.main()
