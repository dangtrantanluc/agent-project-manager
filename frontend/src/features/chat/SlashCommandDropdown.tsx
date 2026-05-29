import clsx from "clsx";
import type { SlashCommand } from "./slashCommands";

type Props = {
  commands: SlashCommand[];
  selectedIndex: number;
  onHover: (index: number) => void;
  onSelect: (command: SlashCommand) => void;
};

export function SlashCommandDropdown({ commands, selectedIndex, onHover, onSelect }: Props) {
  if (!commands.length) return null;

  return (
    <div
      className="absolute bottom-full left-0 z-50 mb-2 w-full max-w-xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-800 dark:bg-slate-900"
      role="listbox"
      aria-label="Slash command suggestions"
    >
      {commands.map((command, index) => {
        const selected = index === selectedIndex;
        return (
          <button
            key={command.name}
            type="button"
            role="option"
            aria-selected={selected}
            className={clsx(
              "flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm transition-colors",
              selected
                ? "bg-brand-50 text-brand-900 dark:bg-brand-950 dark:text-brand-100"
                : "text-slate-800 hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-800",
            )}
            onMouseEnter={() => onHover(index)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onSelect(command)}
          >
            <span className="font-medium">{command.name}</span>
            <span className="text-xs text-slate-500 dark:text-slate-400">{command.description}</span>
            {command.example && (
              <span className="text-xs text-slate-400 dark:text-slate-500">VD: {command.example}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
