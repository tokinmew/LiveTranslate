using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal static class CaptionSurface
    {
        private const int MaxCoverBytes = 32768;
        private const int MaxCoverPixels = 65536;
        private static readonly byte[] PngSignature = { 137, 80, 78, 71, 13, 10, 26, 10 };
        private static readonly Color DefaultPanel = Color.FromArgb(15, 22, 32);
        private static readonly Color LightInk = Color.White;
        private static readonly Color DarkInk = Color.Black;
        internal static readonly Color SpeechTransparencyKey = Color.FromArgb(7, 9, 15);

        private static double Linear(byte value)
        {
            double srgb = value / 255.0;
            return srgb <= .04045 ? srgb / 12.92 : Math.Pow((srgb + .055) / 1.055, 2.4);
        }

        private static double Luminance(Color color)
        {
            return .2126 * Linear(color.R) + .7152 * Linear(color.G) + .0722 * Linear(color.B);
        }

        private static readonly double SwitchLuminance = Math.Sqrt(
            (Luminance(LightInk) + .05) * (Luminance(DarkInk) + .05)) - .05;

        private static int BigEndian(byte[] bytes, int start)
        {
            return (bytes[start] << 24) | (bytes[start + 1] << 16) | (bytes[start + 2] << 8) | bytes[start + 3];
        }

        // The checked OCR worker sends a small RGBA PNG in source-pixel coordinates.
        // Validate the dimensions before asking GDI+ to allocate a decoded image.
        internal static Bitmap DecodeCover(string encoded, Size expected)
        {
            if (String.IsNullOrEmpty(encoded) || encoded.Length > 4 * ((MaxCoverBytes + 2) / 3)
                || expected.Width < 1 || expected.Height < 1 || expected.Width > 2048 || expected.Height > 2048
                || expected.Width * expected.Height > MaxCoverPixels) return null;
            try
            {
                byte[] bytes = Convert.FromBase64String(encoded);
                if (bytes.Length < 33 || bytes.Length > MaxCoverBytes) return null;
                for (int i = 0; i < PngSignature.Length; i++) if (bytes[i] != PngSignature[i]) return null;
                if (BigEndian(bytes, 8) != 13 || BigEndian(bytes, 12) != 0x49484452
                    || BigEndian(bytes, 16) != expected.Width || BigEndian(bytes, 20) != expected.Height
                    || bytes[24] != 8 || bytes[25] != 6 || bytes[26] != 0 || bytes[27] != 0
                    || bytes[28] != 0) return null;
                using (var stream = new MemoryStream(bytes, false))
                using (var decoded = Image.FromStream(stream, false, true))
                {
                    if (decoded.Size != expected) return null;
                    var result = new Bitmap(expected.Width, expected.Height, PixelFormat.Format32bppPArgb);
                    try
                    {
                        using (Graphics canvas = Graphics.FromImage(result))
                        {
                            canvas.CompositingMode = CompositingMode.SourceCopy;
                            canvas.DrawImageUnscaled(decoded, 0, 0);
                        }
                        return result;
                    }
                    catch { result.Dispose(); throw; }
                }
            }
            catch (FormatException) { return null; }
            catch (ArgumentException) { return null; }
            catch (ExternalException) { return null; }
            catch (OutOfMemoryException) { return null; } // GDI+ also reports bad PNG data this way.
        }

        internal static void Paint(Graphics canvas, Size size, bool source, Font face, IList<string> lines,
            int first, int count, int lineHeight, int horizontalPadding, int verticalPadding, int dpi,
            bool highContrast, Bitmap cover, Point coverOffset, Color panel, bool driverFallback = false)
        {
            canvas.PageUnit = GraphicsUnit.Pixel;
            canvas.Clear(driverFallback && !source && !highContrast ? SpeechTransparencyKey : Color.Transparent);
            canvas.SmoothingMode = source ? SmoothingMode.None : SmoothingMode.AntiAlias;
            canvas.CompositingMode = CompositingMode.SourceOver;
            Rectangle bounds = new Rectangle(Point.Empty, size);
            Color backdrop = panel.IsEmpty ? DefaultPanel : panel;
            if (highContrast || (source && (driverFallback || cover == null)))
            {
                using (var background = new SolidBrush(highContrast ? SystemColors.Window : backdrop))
                    canvas.FillRectangle(background, bounds);
            }
            else if (source)
                // Only source-glyph repairs are opaque. Every other pixel belongs to the live desktop.
                canvas.DrawImageUnscaled(cover, coverOffset.X, coverOffset.Y);
            canvas.SmoothingMode = SmoothingMode.AntiAlias;
            if (face == null || lines == null || first < 0 || first >= lines.Count || count <= 0) return;
            count = Math.Min(count, lines.Count - first);
            int padX = Math.Min(Math.Max(0, horizontalPadding), (size.Width - 1) / 2);
            int padY = Math.Min(Math.Max(0, verticalPadding), (size.Height - 1) / 2);
            float availableWidth = size.Width - 2 * padX;
            float rowHeight = Math.Min(Math.Max(1, lineHeight), (size.Height - 2F * padY) / count);
            float top = (size.Height - count * rowHeight) * 0.5F;
            float em = face.Unit == GraphicsUnit.Pixel ? face.Size : face.SizeInPoints * dpi / 72F;
            Color textColor = source && Luminance(backdrop) >= SwitchLuminance ? DarkInk : LightInk;
            Color outlineColor = source ? Color.FromArgb(225, backdrop) : Color.FromArgb(252, 10, 12, 15);
            using (var fill = new SolidBrush(highContrast ? SystemColors.WindowText : textColor))
            using (var outline = new Pen(outlineColor))
            using (var format = StringFormat.GenericTypographic)
            {
                outline.LineJoin = LineJoin.Round;
                format.FormatFlags |= StringFormatFlags.NoWrap;
                for (int i = 0; i < count; i++)
                {
                    string line = lines[first + i];
                    if (String.IsNullOrWhiteSpace(line)) continue;
                    using (var glyphs = new GraphicsPath())
                    {
                        glyphs.AddString(line, face.FontFamily, (int)face.Style, em, PointF.Empty, format);
                        if (glyphs.PointCount == 0) continue;
                        RectangleF ink = glyphs.GetBounds();
                        if (ink.Width <= 0 || ink.Height <= 0) continue;
                        float stroke = highContrast ? 0 : Math.Min(Math.Max(1F, em * (source ? .09F : .17F)),
                            Math.Min(availableWidth, rowHeight) * 0.15F);
                        // Fit the actual outline as well as the advance GDI measured during wrapping.
                        float scale = Math.Min(1F, Math.Min((availableWidth - stroke) / ink.Width,
                            (rowHeight - stroke) / ink.Height));
                        float x = (size.Width - ink.Width * scale) * 0.5F - ink.Left * scale;
                        float y = top + rowHeight * i + (rowHeight - ink.Height * scale) * 0.5F - ink.Top * scale;
                        using (var transform = new Matrix(scale, 0, 0, scale, x, y)) glyphs.Transform(transform);
                        if (stroke > 0)
                        {
                            outline.Width = stroke;
                            canvas.DrawPath(outline, glyphs);
                        }
                        canvas.FillPath(fill, glyphs);
                    }
                }
            }
        }

        // Also usable without a window for deterministic verification of the pixels.
        internal static Bitmap Create(Size size, bool source, Font face, IList<string> lines, int first, int count,
            int lineHeight, int horizontalPadding, int verticalPadding, int dpi, bool highContrast,
            Bitmap cover = null, Point coverOffset = default(Point), Color panel = default(Color))
        {
            var bitmap = new Bitmap(size.Width, size.Height, PixelFormat.Format32bppPArgb);
            try
            {
                using (Graphics graphics = Graphics.FromImage(bitmap))
                    Paint(graphics, size, source, face, lines, first, count, lineHeight, horizontalPadding,
                        verticalPadding, dpi, highContrast, cover, coverOffset, panel);
                return bitmap;
            }
            catch { bitmap.Dispose(); throw; }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BitmapHeader
        {
            internal uint Size;
            internal int Width, Height;
            internal ushort Planes, BitCount;
            internal uint Compression, SizeImage;
            internal int XPelsPerMeter, YPelsPerMeter;
            internal uint ColorsUsed, ColorsImportant;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 1)]
        private struct Blend
        {
            internal byte Operation, Flags, ConstantAlpha, AlphaFormat;
        }

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateCompatibleDC(IntPtr dc);
        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapHeader info, uint usage,
            out IntPtr bits, IntPtr section, uint offset);
        [DllImport("gdi32.dll")]
        private static extern IntPtr SelectObject(IntPtr dc, IntPtr value);
        [DllImport("gdi32.dll")]
        private static extern bool DeleteDC(IntPtr dc);
        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr value);
        [DllImport("user32.dll")]
        private static extern bool UpdateLayeredWindow(IntPtr hwnd, IntPtr destinationDc, ref Point point,
            ref Size size, IntPtr sourceDc, ref Point origin, uint colorKey, ref Blend blend, uint flags);

        internal static bool Render(IntPtr hwnd, Rectangle bounds, bool source, Font face, IList<string> lines,
            int first, int count, int lineHeight, int horizontalPadding, int verticalPadding, int dpi,
            Bitmap cover = null, Rectangle sourceBounds = default(Rectangle), Color panel = default(Color))
        {
            if (hwnd == IntPtr.Zero || bounds.Width < 1 || bounds.Height < 1
                || (long)bounds.Width * bounds.Height > 16777216) return false;
            var header = new BitmapHeader { Size = (uint)Marshal.SizeOf(typeof(BitmapHeader)),
                Width = bounds.Width, Height = -bounds.Height, Planes = 1, BitCount = 32 };
            IntPtr memory = CreateCompatibleDC(IntPtr.Zero);
            if (memory == IntPtr.Zero) return false;
            IntPtr dib = IntPtr.Zero, previous = IntPtr.Zero;
            try
            {
                IntPtr bits;
                dib = CreateDIBSection(memory, ref header, 0, out bits, IntPtr.Zero, 0);
                if (dib == IntPtr.Zero || bits == IntPtr.Zero) return false;
                using (var bitmap = new Bitmap(bounds.Width, bounds.Height, bounds.Width * 4, PixelFormat.Format32bppPArgb, bits))
                using (Graphics canvas = Graphics.FromImage(bitmap))
                    Paint(canvas, bounds.Size, source, face, lines, first, count, lineHeight, horizontalPadding,
                        verticalPadding, dpi, SystemInformation.HighContrast, cover,
                        new Point(sourceBounds.X - bounds.X, sourceBounds.Y - bounds.Y), panel);
                previous = SelectObject(memory, dib);
                if (previous == IntPtr.Zero || previous == new IntPtr(-1)) return false;
                Point position = bounds.Location, origin = Point.Empty;
                Size size = bounds.Size;
                var blend = new Blend { ConstantAlpha = 255, AlphaFormat = 1 }; // AC_SRC_OVER, AC_SRC_ALPHA
                return UpdateLayeredWindow(hwnd, IntPtr.Zero, ref position, ref size, memory, ref origin, 0, ref blend, 2);
            }
            catch (ArgumentException) { return false; }
            catch (ExternalException) { return false; }
            catch (OutOfMemoryException) { return false; }
            finally
            {
                if (previous != IntPtr.Zero && previous != new IntPtr(-1)) SelectObject(memory, previous);
                if (dib != IntPtr.Zero) DeleteObject(dib);
                DeleteDC(memory);
            }
        }
    }
}
