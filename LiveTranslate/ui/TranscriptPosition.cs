using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    // Snapshot the user's place before Rich Edit moves its caret to append text.
    // Character offsets keep wrapped lines aligned when the oldest entry expires.
    internal struct TranscriptPosition
    {
        private const int VerticalScrollBar = 1;
        private const int GetFirstVisibleLine = 0xCE;
        private const int ScrollLines = 0xB6;

        [StructLayout(LayoutKind.Sequential)]
        private struct ScrollInfo
        {
            public int Size, Mask, Minimum, Maximum, Page, Position, TrackPosition;
        }

        [DllImport("user32.dll")]
        private static extern bool GetScrollInfo(IntPtr window, int bar, ref ScrollInfo info);

        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        private int selectionStart, selectionEnd, topCharacter;
        private readonly bool preserve;

        public TranscriptPosition(RichTextBox box)
        {
            selectionStart = box.SelectionStart;
            selectionEnd = selectionStart + box.SelectionLength;
            ScrollInfo info = new ScrollInfo();
            info.Size = Marshal.SizeOf(typeof(ScrollInfo));
            info.Mask = 7; // SIF_RANGE | SIF_PAGE | SIF_POS
            bool aboveBottom = GetScrollInfo(box.Handle, VerticalScrollBar, ref info) &&
                info.Page > 0 && (long)info.Position + info.Page < info.Maximum;
            preserve = aboveBottom || selectionEnd > selectionStart;
            int firstLine = preserve ? FirstLine(box) : 0;
            topCharacter = preserve ? Math.Max(0, box.GetFirstCharIndexFromLine(firstLine)) : 0;
        }

        private static int FirstLine(RichTextBox box)
        {
            return SendMessage(box.Handle, GetFirstVisibleLine, IntPtr.Zero, IntPtr.Zero).ToInt32();
        }

        // Source visibility changes the length of each entry. Keep the reader
        // on the same translation even when dozens of earlier source lines disappear.
        public void Reflow(int[] previousLengths, List<CaptionEntry> entries)
        {
            if (!preserve || previousLengths.Length == 0) return;
            selectionStart = MapCharacter(selectionStart, previousLengths, entries);
            selectionEnd = MapCharacter(selectionEnd, previousLengths, entries);
            topCharacter = MapCharacter(topCharacter, previousLengths, entries);
        }

        private static int MapCharacter(int index, int[] before, List<CaptionEntry> entries)
        {
            int after = 0;
            for (int i = 0; i < before.Length; i++)
            {
                int length = entries[i].RenderedLength;
                if (index < before[i]) return after + Math.Min(index, Math.Max(0, length - 1));
                index -= before[i];
                after += length;
            }
            return after;
        }

        public void Restore(RichTextBox box, int removed)
        {
            if (!preserve)
            {
                box.ScrollToCaret();
                return;
            }
            int start = Math.Max(0, selectionStart - removed);
            int end = Math.Max(start, selectionEnd - removed);
            box.Select(start, end - start);
            int target = box.GetLineFromCharIndex(Math.Max(0, topCharacter - removed));
            SendMessage(box.Handle, ScrollLines, IntPtr.Zero, new IntPtr(target - FirstLine(box)));
        }
    }
}
