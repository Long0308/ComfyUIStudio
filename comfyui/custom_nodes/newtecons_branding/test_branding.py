import importlib.util
from pathlib import Path
import unittest
import json

import torch


spec = importlib.util.spec_from_file_location("branding", Path(__file__).with_name("__init__.py"))
branding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(branding)


class BrandingTests(unittest.TestCase):
    def test_tahoma_dotted_capital_i_is_not_exclamation(self):
        render = branding.NewteconsUnicodeText().render
        _, dotted = render("Ị", 64, "#ffffff", "Tahoma Bold")
        _, bang = render("!", 64, "#ffffff", "Tahoma Bold")
        self.assertTrue(dotted.shape != bang.shape or not torch.equal(dotted, bang))

    def test_mark_removal_changes_only_selected_pixels(self):
        image = torch.full((1, 64, 64, 3), 0.15)
        image[:, 25:30, 25:30] = 1
        result, mask = branding.NewteconsLocalMarkRemoval().remove(image, json.dumps([
            {"x": 20, "y": 20, "width": 20, "height": 20, "mode": "bright", "grow": 1}]))
        self.assertTrue(torch.equal(result[mask == 0], image[mask == 0]))
        self.assertLess(result[:, 25:30, 25:30].max().item(), 0.2)

    def test_out_of_bounds_mark_removal_is_rejected(self):
        with self.assertRaises(ValueError):
            branding.NewteconsLocalMarkRemoval().remove(torch.zeros((1, 32, 32, 3)), json.dumps([
                {"x": 30, "y": 30, "width": 8, "height": 8}]))

    def test_vietnamese_glyphs_are_distinct_and_nonempty(self):
        render = branding.NewteconsUnicodeText().render
        _, accented = render("THIẾT BỊ", 64, "#ffffff")
        _, plain = render("THIET BI", 64, "#ffffff")
        self.assertGreater(accented.sum().item(), 0)
        self.assertTrue(accented.shape != plain.shape or not torch.equal(accented, plain))

    def test_multiline_centered_text_rounds_fractional_font_bounds(self):
        image, mask = branding.NewteconsUnicodeText().render("KHỐI\nKỸ THUẬT", 64, "#ffffff")
        self.assertEqual(tuple(image.shape[1:3]), tuple(mask.shape[1:3]))
        self.assertGreater(mask.sum().item(), 0)

    def test_composite_preserves_pixels_outside_quad(self):
        destination = torch.rand((1, 128, 128, 3))
        source = torch.ones((1, 16, 16, 3))
        mask = torch.ones((1, 16, 16))
        result, = branding.NewteconsPerspectiveComposite().composite(
            destination, source, mask, 40, 40, 80, 42, 78, 82, 42, 80)
        self.assertTrue(torch.equal(result[:, :30], destination[:, :30]))
        self.assertTrue(torch.equal(result[:, 90:], destination[:, 90:]))
        self.assertTrue(torch.equal(result[:, :, :30], destination[:, :, :30]))
        self.assertTrue(torch.equal(result[:, 50:70, 50:70], torch.ones((1, 20, 20, 3))))

    def test_transparent_source_leaves_identity_pixels_unchanged(self):
        destination = torch.rand((1, 64, 64, 3))
        result, = branding.NewteconsPerspectiveComposite().composite(
            destination, torch.ones((1, 8, 8, 3)), torch.zeros((1, 8, 8)),
            10, 10, 50, 10, 50, 50, 10, 50)
        self.assertTrue(torch.equal(result, destination))

    def test_invalid_quads_are_rejected_before_compositing(self):
        for quad in [(20, 20, 80, 80, 80, 20, 20, 80),
                     (20, 20, 20, 20, 80, 80, 20, 80),
                     (0, 0, 10, 0, 20, 0, 30, 0),
                     (0, 0, float("nan"), 0, 10, 10, 0, 10)]:
            with self.subTest(quad=quad), self.assertRaises(ValueError):
                branding.NewteconsPerspectiveComposite().composite(
                    torch.zeros((1, 100, 100, 3)), torch.ones((1, 8, 8, 3)),
                    torch.ones((1, 8, 8)), *quad)


if __name__ == "__main__":
    unittest.main()
