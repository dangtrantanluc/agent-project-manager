import { formatDate } from "@/lib/format";

/** Một mục ghi chú: ngày (nếu có prefix [YYYY-MM-DD]) + nội dung. */
type Entry = { date: string | null; text: string };

const _DATE_PREFIX = /^\[(\d{4}-\d{2}-\d{2})\]\s*(.*)$/;

/** Tách text dạng nhiều dòng "[YYYY-MM-DD] nội dung" thành các mục có ngày.
 * Dòng không có prefix ngày (dữ liệu cũ) vẫn giữ, date=null. */
export function parseDatedNotes(text: string | null | undefined): Entry[] {
  if (!text) return [];
  const out: Entry[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(_DATE_PREFIX);
    if (m) out.push({ date: m[1], text: m[2] });
    else out.push({ date: null, text: line });
  }
  return out;
}

/**
 * Hiển thị lịch sử ghi chú (kết quả/khó khăn) dạng timeline — mới nhất lên đầu.
 * Mỗi mục: mốc ngày + nội dung. Dùng cho field tasks.result / tasks.issues vốn
 * được agent append theo dạng "[ngày] nội dung".
 */
export function DatedNotesList({
  text,
  emptyText = "Chưa có ghi chú.",
}: {
  text: string | null | undefined;
  emptyText?: string;
}) {
  const entries = parseDatedNotes(text);
  if (entries.length === 0) {
    return <p className="py-1 text-xs text-slate-400">{emptyText}</p>;
  }
  // Append theo thời gian -> đảo để mới nhất lên đầu.
  const ordered = [...entries].reverse();
  return (
    <ul className="space-y-1.5">
      {ordered.map((e, i) => (
        <li
          key={i}
          className="flex gap-2 rounded border border-slate-100 bg-white p-2 text-xs dark:border-slate-800 dark:bg-slate-900"
        >
          <span className="shrink-0 font-mono text-slate-400">
            {e.date ? `📅 ${formatDate(e.date)}` : "•"}
          </span>
          <span className="min-w-0 whitespace-pre-wrap break-words">{e.text}</span>
        </li>
      ))}
    </ul>
  );
}
