import { FormEvent, useState } from "react";
import { SlashCommandDropdown } from "./SlashCommandDropdown";
import { useSlashCommandAutocomplete } from "./useSlashCommandAutocomplete";
import type { SlashCommand } from "./slashCommands";

type Props = {
  onSend: (message: string) => void | Promise<void>;
  placeholder?: string;
  commands?: SlashCommand[];
  disabled?: boolean;
};

export function ChatInput({ onSend, placeholder = "Nhập tin nhắn...", commands, disabled }: Props) {
  const [value, setValue] = useState("");
  const autocomplete = useSlashCommandAutocomplete({ value, onChange: setValue, commands });

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = value.trim();
    if (!message || disabled) return;
    await onSend(message);
    setValue("");
  };

  return (
    <form className="relative" onSubmit={submit}>
      {autocomplete.isOpen && (
        <SlashCommandDropdown
          commands={autocomplete.filteredCommands}
          selectedIndex={autocomplete.selectedIndex}
          onHover={autocomplete.setSelectedIndex}
          onSelect={autocomplete.selectCommand}
        />
      )}

      <div className="flex gap-2">
        <input
          className="input"
          disabled={disabled}
          value={value}
          placeholder={placeholder}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={autocomplete.onKeyDown}
          autoComplete="off"
        />
        <button className="btn-primary" type="submit" disabled={disabled || !value.trim()}>
          Gửi
        </button>
      </div>
    </form>
  );
}
