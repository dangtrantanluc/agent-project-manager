import type { Tag } from "@/features/tags/api";

/** Hiển thị danh sách nhãn dạng chip màu (màu lấy từ tag.color hex). */
export function TagChips({
  tags,
  className,
}: {
  tags: Pick<Tag, "id" | "name" | "color">[];
  className?: string;
}) {
  if (!tags?.length) return null;
  return (
    <div className={`flex flex-wrap gap-1 ${className ?? ""}`}>
      {tags.map((t) => (
        <span
          key={t.id}
          className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
          // hex 8 số: +"22" ~ nền nhạt 13%, +"55" viền 33%.
          style={{ backgroundColor: `${t.color}22`, color: t.color, border: `1px solid ${t.color}55` }}
        >
          {t.name}
        </span>
      ))}
    </div>
  );
}
