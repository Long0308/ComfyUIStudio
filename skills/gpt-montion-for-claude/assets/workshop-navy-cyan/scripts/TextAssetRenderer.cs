using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security;
using System.Text;

public sealed class TextAssetResult
{
    public int Width { get; set; }
    public int Height { get; set; }
    public float FontSizePx { get; set; }
    public string FontFamily { get; set; }
    public string FontStyle { get; set; }
    public long TransparentPixels { get; set; }
    public long PaintedPixels { get; set; }
    public long AntialiasedPixels { get; set; }
    public int MinimumPaintX { get; set; }
    public int MinimumPaintY { get; set; }
    public int MaximumPaintX { get; set; }
    public int MaximumPaintY { get; set; }
    public int PathPointCount { get; set; }
}

// Single phrase outlines preserve the font's shaping and Vietnamese diacritics.
// These are event typography assets; corporate artwork is never generated here.
public static class TextAssetRenderer
{
    private static string N(float n) { return n.ToString("0.####", CultureInfo.InvariantCulture); }
    private static string E(string s) { return SecurityElement.Escape(s); }

    private static string SvgPath(GraphicsPath outline)
    {
        PointF[] p = outline.PathPoints;
        byte[] t = outline.PathTypes;
        var d = new StringBuilder();
        for (int i = 0; i < p.Length; i++)
        {
            int kind = t[i] & 7;
            if (kind == 0) d.Append("M").Append(N(p[i].X)).Append(" ").Append(N(p[i].Y));
            else if (kind == 1) d.Append("L").Append(N(p[i].X)).Append(" ").Append(N(p[i].Y));
            else if (kind == 3)
            {
                if (i + 2 >= p.Length || (t[i + 1] & 7) != 3 || (t[i + 2] & 7) != 3)
                    throw new InvalidOperationException("Incomplete cubic outline.");
                d.Append("C").Append(N(p[i].X)).Append(" ").Append(N(p[i].Y)).Append(" ")
                    .Append(N(p[i + 1].X)).Append(" ").Append(N(p[i + 1].Y)).Append(" ")
                    .Append(N(p[i + 2].X)).Append(" ").Append(N(p[i + 2].Y));
                i += 2;
            }
            else throw new InvalidOperationException("Unsupported outline point type.");
            if ((t[i] & 128) != 0) d.Append("Z");
        }
        return d.ToString();
    }

    public static TextAssetResult Render(string id, string text, string pngFile, string svgFile,
        float requestedSize, bool italic, string colorHex, int maximumWidth, string fontFile)
    {
        if (string.IsNullOrWhiteSpace(text)) throw new ArgumentException("Text is required.");
        if (maximumWidth < 200 || maximumWidth > 3840) throw new ArgumentOutOfRangeException("maximumWidth");
        if (requestedSize < 24 || requestedSize > 800) throw new ArgumentOutOfRangeException("requestedSize");
        if (!File.Exists(fontFile)) throw new FileNotFoundException("Pinned font is required.", fontFile);
        using (var collection = new PrivateFontCollection())
        {
        collection.AddFontFile(fontFile);
        // Resolve from the explicit hashed font file, not the machine's default font registry.
        using (var family = new FontFamily("Roboto Condensed", collection))
        using (var format = (StringFormat)StringFormat.GenericTypographic.Clone())
        using (var outline = new GraphicsPath(FillMode.Alternate))
        {
            if (!string.Equals(family.Name, "Roboto Condensed", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Pinned Roboto Condensed is required.");
            FontStyle style = italic ? FontStyle.Italic : FontStyle.Bold;
            if (!family.IsStyleAvailable(style)) throw new InvalidOperationException("Required font style is unavailable.");
            format.FormatFlags |= StringFormatFlags.NoWrap | StringFormatFlags.NoClip | StringFormatFlags.MeasureTrailingSpaces;
            format.Trimming = StringTrimming.None;
            float size = requestedSize;
            int padding, width, height;
            RectangleF bounds;
            while (true)
            {
                outline.Reset();
                outline.AddString(text, family, (int)style, size, PointF.Empty, format);
                bounds = outline.GetBounds();
                padding = (int)Math.Ceiling(size * .12f) + 8;
                width = (int)Math.Ceiling(bounds.Width) + padding * 2;
                height = (int)Math.Ceiling(bounds.Height) + padding * 2;
                if (width <= maximumWidth) break;
                size -= .5f;
                if (size < 24) throw new InvalidOperationException("Text exceeds bounded raster width.");
            }
            using (var move = new Matrix())
            {
                move.Translate(padding - bounds.Left, padding - bounds.Top);
                outline.Transform(move);
            }
            var result = new TextAssetResult { Width = width, Height = height, FontSizePx = size,
                FontFamily = family.Name, FontStyle = style.ToString(), PathPointCount = outline.PointCount,
                MinimumPaintX = width, MinimumPaintY = height, MaximumPaintX = -1, MaximumPaintY = -1 };
            using (var bitmap = new Bitmap(width, height, PixelFormat.Format32bppArgb))
            {
                using (var graphics = Graphics.FromImage(bitmap))
                using (var brush = new SolidBrush(ColorTranslator.FromHtml(colorHex)))
                {
                    graphics.Clear(Color.Transparent);
                    graphics.SmoothingMode = SmoothingMode.AntiAlias;
                    graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
                    graphics.FillPath(brush, outline);
                }
                BitmapData data = bitmap.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    byte[] row = new byte[width * 4];
                    for (int y = 0; y < height; y++)
                    {
                        Marshal.Copy(IntPtr.Add(data.Scan0, y * data.Stride), row, 0, row.Length);
                        for (int x = 0; x < width; x++)
                        {
                            int alpha = row[x * 4 + 3];
                            if (alpha == 0) { result.TransparentPixels++; continue; }
                            result.PaintedPixels++;
                            if (alpha < 255) result.AntialiasedPixels++;
                            result.MinimumPaintX = Math.Min(result.MinimumPaintX, x);
                            result.MaximumPaintX = Math.Max(result.MaximumPaintX, x);
                            result.MinimumPaintY = Math.Min(result.MinimumPaintY, y);
                            result.MaximumPaintY = Math.Max(result.MaximumPaintY, y);
                        }
                    }
                }
                finally { bitmap.UnlockBits(data); }
                if (result.PaintedPixels == 0 || result.TransparentPixels == 0 || result.MinimumPaintX < 2 ||
                    result.MinimumPaintY < 2 || result.MaximumPaintX > width - 3 || result.MaximumPaintY > height - 3)
                    throw new InvalidOperationException("Empty or clipped text outline.");
                bitmap.Save(pngFile, ImageFormat.Png);
            }
            string svg = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" +
                "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + width + "\" height=\"" + height +
                "\" viewBox=\"0 0 " + width + " " + height + "\" role=\"img\" aria-labelledby=\"" + E(id) + "_TITLE\">\n" +
                "<title id=\"" + E(id) + "_TITLE\">" + E(text) + "</title>\n" +
                "<metadata>Pinned Roboto Condensed; " + style + "; " + N(size) + "px; outlined using Windows GDI+; no runtime font dependency.</metadata>\n" +
                "<g id=\"" + E(id) + "\" data-text=\"" + E(text) + "\"><g id=\"" + E(id) +
                "_RUN_01\"><path fill=\"" + E(colorHex) + "\" fill-rule=\"evenodd\" d=\"" + SvgPath(outline) + "\"/></g></g>\n</svg>\n";
            File.WriteAllText(svgFile, svg, new UTF8Encoding(false));
            return result;
        }
        }
    }
}
