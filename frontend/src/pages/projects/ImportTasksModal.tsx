import { useMemo, useRef, useState } from "react";
import { AlertCircle, Brain, CheckCircle, ChevronLeft, FileSpreadsheet, Upload, X } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { apiClient } from "@/lib/apiClient";
import { toast } from "sonner";

interface PreviewRow {
  row_index: number;
  name: string;
  priority: string;
  deadline: string | null;
  start_date: string | null;
  assignee_name: string | null;
  module: string | null;
  description: string | null;
  status: string;
  skip: boolean;
}

interface ParseResult {
  sheets: string[];
  active_sheet: string;
  column_map: Record<string, number>;
  rows: PreviewRow[];
}

interface AiMilestone {
  tempId: string;
  name: string;
  description: string | null;
  dueDate: string | null;
  status: string | null;
  skip: boolean;
}

interface AiTask {
  tempMilestoneId: string | null;
  name: string;
  description: string | null;
  priority: string;
  status: string;
  deadline: string | null;
  assigneeName: string | null;
  sourceSheet: string | null;
  skip: boolean;
}

interface AiPreview {
  projectName: string;
  summary: string;
  milestones: AiMilestone[];
  tasks: AiTask[];
}

type Step = "upload" | "preview" | "result";
type ImportMode = "excel" | "ai";
type ImportResult = {
  created: number;
  createdMilestones: number;
  createdTasks: number;
  errors: Array<{ row_index?: number; name?: string; message: string }>;
};

const PRIORITY_OPTIONS = ["URGENT", "HIGH", "MEDIUM", "LOW"];
const STATUS_OPTIONS = ["TODO", "IN_PROGRESS", "DONE", "CANCELLED"];
const MILESTONE_STATUS_OPTIONS = ["", "PLANNED", "IN_PROGRESS", "DONE"];
const PRIORITY_LABELS: Record<string, string> = {
  URGENT: "Urgent",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
};

export function ImportTasksModal({
  projectId,
  open,
  onClose,
  onSuccess,
}: {
  projectId: number;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<ImportMode>("excel");
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [sheets, setSheets] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState<string>("");
  const [rows, setRows] = useState<PreviewRow[]>([]);
  const [aiProjectName, setAiProjectName] = useState("");
  const [aiSummary, setAiSummary] = useState("");
  const [aiMilestones, setAiMilestones] = useState<AiMilestone[]>([]);
  const [aiTasks, setAiTasks] = useState<AiTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const reset = () => {
    setMode("excel");
    setStep("upload");
    setFile(null);
    setSheets([]);
    setActiveSheet("");
    setRows([]);
    setAiProjectName("");
    setAiSummary("");
    setAiMilestones([]);
    setAiTasks([]);
    setResult(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const fetchPreview = async (f: File, sheet?: string) => {
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      if (mode === "ai") {
        const { data } = await apiClient.post<AiPreview>(`/projects/${projectId}/ai-import/preview`, fd);
        setAiProjectName(data.projectName);
        setAiSummary(data.summary);
        setAiMilestones(data.milestones.map((m) => ({ ...m, skip: m.skip ?? false })));
        setAiTasks(data.tasks.map((t) => ({ ...t, skip: t.skip ?? false })));
      } else {
        const { data } = await apiClient.post<ParseResult>(
          `/projects/${projectId}/import-tasks/preview`,
          fd,
          { params: sheet ? { sheet } : undefined },
        );
        setSheets(data.sheets);
        setActiveSheet(data.active_sheet);
        setRows(data.rows.map((r) => ({ ...r, skip: false })));
      }
      setStep("preview");
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? "Không thể đọc file");
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const handleSheetChange = async (sheet: string) => {
    setActiveSheet(sheet);
    if (file) await fetchPreview(file, sheet);
  };

  const handleConfirm = async () => {
    const skippedMilestones = new Set(aiMilestones.filter((m) => m.skip).map((m) => m.tempId));
    const selectedTaskCount = mode === "ai"
      ? aiTasks.filter((t) => !t.skip && (!t.tempMilestoneId || !skippedMilestones.has(t.tempMilestoneId))).length
      : rows.filter((r) => !r.skip).length;
    if (!selectedTaskCount) {
      toast.error("Không có task nào được chọn");
      return;
    }
    setLoading(true);
    try {
      if (mode === "ai") {
        const { data } = await apiClient.post<Pick<ImportResult, "createdMilestones" | "createdTasks" | "errors">>(
          `/projects/${projectId}/ai-import/confirm`,
          {
            projectName: aiProjectName,
            summary: aiSummary,
            milestones: aiMilestones,
            tasks: aiTasks,
          },
        );
        setResult({ created: data.createdTasks, ...data });
        if (data.createdTasks > 0 || data.createdMilestones > 0) onSuccess();
      } else {
        const toCreate = rows.filter((r) => !r.skip);
        const { data } = await apiClient.post<{ created: number; errors: ImportResult["errors"] }>(
          `/projects/${projectId}/import-tasks/confirm`,
          { rows: toCreate },
        );
        setResult({ created: data.created, createdTasks: data.created, createdMilestones: 0, errors: data.errors });
        if (data.created > 0) onSuccess();
      }
      setStep("result");
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? "Lỗi khi tạo tasks");
    } finally {
      setLoading(false);
    }
  };

  const updateRow = (idx: number, field: keyof PreviewRow, value: string | boolean | null) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)));
  };

  const updateAiMilestone = (idx: number, field: keyof AiMilestone, value: string | boolean | null) => {
    setAiMilestones((prev) => prev.map((m, i) => (i === idx ? { ...m, [field]: value } : m)));
  };

  const updateAiTask = (idx: number, field: keyof AiTask, value: string | boolean | null) => {
    setAiTasks((prev) => prev.map((t, i) => (i === idx ? { ...t, [field]: value } : t)));
  };

  const skippedMilestoneIds = useMemo(
    () => new Set(aiMilestones.filter((m) => m.skip).map((m) => m.tempId)),
    [aiMilestones],
  );
  const selectedCount = mode === "ai"
    ? aiTasks.filter((t) => !t.skip && (!t.tempMilestoneId || !skippedMilestoneIds.has(t.tempMilestoneId))).length
    : rows.filter((r) => !r.skip).length;
  const selectedMilestones = aiMilestones.filter((m) => !m.skip).length;

  const groupedAiTasks = useMemo(() => {
    const groups = aiMilestones.map((milestone) => ({
      milestone,
      tasks: aiTasks
        .map((task, index) => ({ task, index }))
        .filter(({ task }) => task.tempMilestoneId === milestone.tempId),
    }));
    const unassigned = aiTasks
      .map((task, index) => ({ task, index }))
      .filter(({ task }) => !task.tempMilestoneId);
    if (unassigned.length) {
      groups.push({
        milestone: {
          tempId: "",
          name: "Không có milestone",
          description: null,
          dueDate: null,
          status: null,
          skip: false,
        },
        tasks: unassigned,
      });
    }
    return groups;
  }, [aiMilestones, aiTasks]);

  const title =
    step === "upload" ? "Import tasks từ Excel"
    : step === "preview" && mode === "ai" ? `AI preview: ${selectedMilestones} milestone · ${selectedCount} task`
    : step === "preview" ? `Preview: ${selectedCount}/${rows.length} tasks`
    : "Kết quả import";

  return (
    <Modal open={open} onClose={handleClose} title={title} size="lg">
      {step === "upload" && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 p-1 dark:border-slate-700">
            <button
              className={`flex items-center justify-center gap-2 rounded px-3 py-2 text-sm ${mode === "excel" ? "bg-brand-600 text-white" : "text-slate-600 dark:text-slate-300"}`}
              onClick={() => setMode("excel")}
              type="button"
            >
              <FileSpreadsheet className="h-4 w-4" /> Import Excel
            </button>
            <button
              className={`flex items-center justify-center gap-2 rounded px-3 py-2 text-sm ${mode === "ai" ? "bg-brand-600 text-white" : "text-slate-600 dark:text-slate-300"}`}
              onClick={() => setMode("ai")}
              type="button"
            >
              <Brain className="h-4 w-4" /> AI Planning
            </button>
          </div>

          <div
            className="flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed border-slate-300 p-8 text-center hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:hover:border-brand-600"
            onClick={() => fileRef.current?.click()}
          >
            <Upload className="h-8 w-8 text-slate-400" />
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Chọn file .xlsx để {mode === "ai" ? "AI extract milestone và task" : "import task theo rule hiện tại"}
            </p>
            {file && (
              <span className="rounded bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700 dark:bg-brand-900/40 dark:text-brand-300">
                {file.name}
              </span>
            )}
          </div>
          <input ref={fileRef} type="file" accept=".xlsx" className="hidden" onChange={handleFileChange} />

          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={handleClose}>Hủy</button>
            <button className="btn-primary" disabled={!file || loading} onClick={() => file && fetchPreview(file)}>
              {loading ? "Đang xử lý..." : "Tiếp tục"}
            </button>
          </div>
        </div>
      )}

      {step === "preview" && mode === "excel" && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <button className="btn-ghost flex items-center gap-1 text-xs" onClick={() => setStep("upload")}>
              <ChevronLeft className="h-3 w-3" /> Quay lại
            </button>
            {sheets.length > 1 && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Sheet:</span>
                <select value={activeSheet} onChange={(e) => handleSheetChange(e.target.value)} className="input py-0.5 text-xs" disabled={loading}>
                  {sheets.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            )}
            <div className="ml-auto flex items-center gap-1">
              <input
                type="checkbox"
                id="select-all"
                checked={selectedCount === rows.length && rows.length > 0}
                onChange={(e) => setRows((prev) => prev.map((r) => ({ ...r, skip: !e.target.checked })))}
              />
              <label htmlFor="select-all" className="text-xs text-slate-500">Chọn tất cả</label>
            </div>
          </div>

          {rows.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">Không tìm thấy task nào trong sheet này. Thử chọn sheet khác.</p>
          ) : (
            <div className="max-h-96 overflow-y-auto rounded border border-slate-200 dark:border-slate-700">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800">
                  <tr>
                    <th className="w-8 px-2 py-2 text-center">#</th>
                    <th className="px-2 py-2 text-left">Tên task</th>
                    <th className="w-24 px-2 py-2 text-left">Priority</th>
                    <th className="w-28 px-2 py-2 text-left">Deadline</th>
                    <th className="w-28 px-2 py-2 text-left">Người làm</th>
                    <th className="w-20 px-2 py-2 text-center">Bỏ qua</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, idx) => (
                    <tr key={row.row_index} className={`border-t border-slate-100 dark:border-slate-800 ${row.skip ? "opacity-40" : ""}`}>
                      <td className="px-2 py-1 text-center text-slate-400">{idx + 1}</td>
                      <td className="px-2 py-1">
                        <input className="w-full bg-transparent outline-none focus:underline" value={row.name} onChange={(e) => updateRow(idx, "name", e.target.value)} disabled={row.skip} />
                        {row.module && <span className="text-slate-400">[{row.module}]</span>}
                      </td>
                      <td className="px-2 py-1">
                        <select value={row.priority} onChange={(e) => updateRow(idx, "priority", e.target.value)} className="w-full bg-transparent text-xs outline-none" disabled={row.skip}>
                          {PRIORITY_OPTIONS.map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p] ?? p}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-1">
                        <input type="date" className="w-full bg-transparent text-xs outline-none" value={row.deadline ?? ""} onChange={(e) => updateRow(idx, "deadline", e.target.value || null)} disabled={row.skip} />
                      </td>
                      <td className="px-2 py-1">
                        <input className="w-full bg-transparent outline-none focus:underline" value={row.assignee_name ?? ""} onChange={(e) => updateRow(idx, "assignee_name", e.target.value || null)} placeholder="-" disabled={row.skip} />
                      </td>
                      <td className="px-2 py-1 text-center">
                        <button onClick={() => updateRow(idx, "skip", !row.skip)} className={`rounded p-0.5 ${row.skip ? "text-slate-400 hover:text-slate-600" : "text-rose-500 hover:text-rose-700"}`}>
                          <X className="h-3 w-3" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <PreviewActions selectedCount={selectedCount} loading={loading} onClose={handleClose} onConfirm={handleConfirm} />
        </div>
      )}

      {step === "preview" && mode === "ai" && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <button className="btn-ghost flex items-center gap-1 text-xs" onClick={() => setStep("upload")}>
              <ChevronLeft className="h-3 w-3" /> Quay lại
            </button>
            <p className="text-xs text-slate-500">{aiProjectName || "AI Planning"} · {aiSummary}</p>
          </div>

          <div className="max-h-[28rem] space-y-3 overflow-y-auto pr-1">
            {groupedAiTasks.map(({ milestone, tasks }, milestoneIndex) => (
              <section key={milestone.tempId} className={`rounded-md border border-slate-200 p-3 dark:border-slate-700 ${milestone.skip ? "opacity-50" : ""}`}>
                {milestone.tempId ? (
                  <>
                    <div className="grid gap-2 md:grid-cols-[1.5fr_9rem_8rem_2rem]">
                      <input className="input py-1 text-sm font-medium" value={milestone.name} onChange={(e) => updateAiMilestone(milestoneIndex, "name", e.target.value)} disabled={milestone.skip} />
                      <input type="date" className="input py-1 text-sm" value={milestone.dueDate ?? ""} onChange={(e) => updateAiMilestone(milestoneIndex, "dueDate", e.target.value || null)} disabled={milestone.skip} />
                      <select className="input py-1 text-sm" value={milestone.status ?? ""} onChange={(e) => updateAiMilestone(milestoneIndex, "status", e.target.value || null)} disabled={milestone.skip}>
                        {MILESTONE_STATUS_OPTIONS.map((s) => <option key={s || "none"} value={s}>{s || "Status"}</option>)}
                      </select>
                      <button className="rounded p-1 text-rose-500 hover:bg-rose-50" onClick={() => updateAiMilestone(milestoneIndex, "skip", !milestone.skip)}>
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    <textarea className="input mt-2 min-h-16 text-xs" value={milestone.description ?? ""} onChange={(e) => updateAiMilestone(milestoneIndex, "description", e.target.value || null)} disabled={milestone.skip} />
                  </>
                ) : (
                  <p className="text-sm font-medium text-slate-600 dark:text-slate-300">{milestone.name}</p>
                )}

                <div className="mt-3 space-y-2">
                  {tasks.map(({ task, index }) => (
                    <div key={`${milestone.tempId}-${index}`} className={`grid gap-2 rounded border border-slate-100 p-2 text-xs dark:border-slate-800 md:grid-cols-[1.5fr_7rem_7rem_8rem_1fr_2rem] ${task.skip ? "opacity-40" : ""}`}>
                      <input className="bg-transparent font-medium outline-none focus:underline" value={task.name} onChange={(e) => updateAiTask(index, "name", e.target.value)} disabled={task.skip || milestone.skip} />
                      <select className="bg-transparent outline-none" value={task.priority} onChange={(e) => updateAiTask(index, "priority", e.target.value)} disabled={task.skip || milestone.skip}>
                        {PRIORITY_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
                      </select>
                      <select className="bg-transparent outline-none" value={task.status} onChange={(e) => updateAiTask(index, "status", e.target.value)} disabled={task.skip || milestone.skip}>
                        {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                      <input type="date" className="bg-transparent outline-none" value={task.deadline ?? ""} onChange={(e) => updateAiTask(index, "deadline", e.target.value || null)} disabled={task.skip || milestone.skip} />
                      <input className="bg-transparent outline-none focus:underline" value={task.assigneeName ?? ""} onChange={(e) => updateAiTask(index, "assigneeName", e.target.value || null)} placeholder="Assignee" disabled={task.skip || milestone.skip} />
                      <button className="rounded p-1 text-rose-500 hover:bg-rose-50" onClick={() => updateAiTask(index, "skip", !task.skip)}>
                        <X className="h-3 w-3" />
                      </button>
                      {(task.description || task.sourceSheet) && (
                        <p className="md:col-span-6 text-slate-400">{task.description}{task.sourceSheet ? ` · ${task.sourceSheet}` : ""}</p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <PreviewActions selectedCount={selectedCount} loading={loading} onClose={handleClose} onConfirm={handleConfirm} />
        </div>
      )}

      {step === "result" && result && (
        <div className="space-y-4">
          <div className="flex flex-col items-center gap-3 py-4">
            <CheckCircle className="h-10 w-10 text-emerald-500" />
            <p className="text-lg font-semibold">Hoàn thành!</p>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Đã tạo <span className="font-bold text-emerald-600">{result.createdTasks}</span> tasks
              {result.createdMilestones > 0 && (
                <span> · <span className="font-bold text-emerald-600">{result.createdMilestones}</span> milestones</span>
              )}
              {result.errors.length > 0 && <span className="text-amber-600"> · {result.errors.length} lỗi</span>}
            </p>
          </div>

          {result.errors.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/30">
              <div className="mb-2 flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-amber-600" />
                <span className="text-xs font-semibold text-amber-700 dark:text-amber-400">Chi tiết lỗi</span>
              </div>
              <ul className="space-y-1">
                {result.errors.map((err, idx) => (
                  <li key={`${err.row_index ?? err.name ?? idx}`} className="text-xs text-amber-700 dark:text-amber-400">
                    {err.row_index ? `Dòng ${err.row_index}` : err.name ?? "Item"}: {err.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex justify-end">
            <button className="btn-primary" onClick={handleClose}>Đóng</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function PreviewActions({
  selectedCount,
  loading,
  onClose,
  onConfirm,
}: {
  selectedCount: number;
  loading: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="flex justify-end gap-2">
      <button className="btn-ghost" onClick={onClose}>Hủy</button>
      <button className="btn-primary" disabled={selectedCount === 0 || loading} onClick={onConfirm}>
        {loading ? "Đang tạo..." : `Tạo ${selectedCount} task`}
      </button>
    </div>
  );
}
