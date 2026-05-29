import { useCallback, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
import { slashCommands as defaultCommands, type SlashCommand } from "./slashCommands";

type TextInputElement = HTMLInputElement | HTMLTextAreaElement;

type Options = {
  value: string;
  onChange: (nextValue: string) => void;
  commands?: SlashCommand[];
};

const slashQueryRe = /^\/([a-zA-Z0-9_-]*)$/;

export function useSlashCommandAutocomplete({
  value,
  onChange,
  commands = defaultCommands,
}: Options) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const match = value.match(slashQueryRe);
  const query = match?.[1].toLowerCase() ?? null;

  const filteredCommands = useMemo(() => {
    if (query === null) return [];
    return commands.filter((command) => command.name.slice(1).toLowerCase().startsWith(query));
  }, [commands, query]);

  const isOpen = Boolean(value) && query !== null && filteredCommands.length > 0;

  const clampIndex = useCallback(
    (index: number) => {
      if (!filteredCommands.length) return 0;
      return (index + filteredCommands.length) % filteredCommands.length;
    },
    [filteredCommands.length],
  );

  const selectCommand = useCallback(
    (command: SlashCommand) => {
      onChange(`${command.name} `);
      setSelectedIndex(0);
    },
    [onChange],
  );

  const close = useCallback(() => {
    setSelectedIndex(0);
  }, []);

  const onKeyDown = useCallback(
    (event: KeyboardEvent<TextInputElement>) => {
      if (!isOpen) return;

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((current) => clampIndex(current + 1));
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex((current) => clampIndex(current - 1));
        return;
      }

      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const command = filteredCommands[selectedIndex] ?? filteredCommands[0];
        if (command) selectCommand(command);
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        onChange("");
        close();
      }
    },
    [clampIndex, close, filteredCommands, isOpen, onChange, selectCommand, selectedIndex],
  );

  return {
    isOpen,
    filteredCommands,
    selectedIndex: isOpen ? Math.min(selectedIndex, filteredCommands.length - 1) : 0,
    setSelectedIndex,
    selectCommand,
    close,
    onKeyDown,
  };
}
