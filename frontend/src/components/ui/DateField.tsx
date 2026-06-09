import type { FieldValues, Path, UseFormReturn } from "react-hook-form";

/** Ngày hôm nay ở dạng YYYY-MM-DD theo giờ local (không lệch timezone như toISOString). */
export function todayLocalISO(): string {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - tz).toISOString().slice(0, 10);
}

/**
 * Ô nhập ngày gắn với react-hook-form, kèm nút "Hôm nay" để điền nhanh ngày hiện tại.
 * Dùng: <DateField form={form} name="deadline" />
 */
export function DateField<T extends FieldValues>({
  form,
  name,
  className = "input",
  todayLabel = "Hôm nay",
}: {
  form: UseFormReturn<T>;
  name: Path<T>;
  className?: string;
  todayLabel?: string;
}) {
  return (
    <div className="flex items-center gap-1">
      <input type="date" className={className} {...form.register(name)} />
      <button
        type="button"
        className="whitespace-nowrap rounded-md border border-slate-200 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        onClick={() =>
          form.setValue(name, todayLocalISO() as any, { shouldDirty: true, shouldValidate: true })
        }
        title="Chọn ngày hôm nay"
      >
        {todayLabel}
      </button>
    </div>
  );
}
