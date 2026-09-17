import { Command as Cmdk } from "cmdk";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Dialog } from "@/shared/ui/Dialog";
import { Kbd } from "@/shared/ui/Misc";

import { formatShortcut, useCommands, type Command } from "./commands";

function groupCommands(commands: Iterable<Command>) {
  const groups = new Map<string, Command[]>();
  for (const command of commands) {
    const list = groups.get(command.group) ?? [];
    list.push(command);
    groups.set(command.group, list);
  }
  return groups;
}

export function CommandPalette() {
  const { t } = useTranslation();
  const { commands, paletteOpen, setPaletteOpen } = useCommands();
  const groups = useMemo(() => groupCommands(commands.values()), [commands]);

  return (
    <Dialog
      open={paletteOpen}
      onOpenChange={setPaletteOpen}
      title={t("palette.title")}
      className="p-0 [&>div:first-child]:hidden"
    >
      <Cmdk label={t("palette.title")} className="overflow-hidden rounded-xl">
        <Cmdk.Input
          autoFocus
          placeholder={t("palette.placeholder")}
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted"
        />
        <Cmdk.List className="max-h-80 overflow-y-auto p-2">
          <Cmdk.Empty className="px-3 py-6 text-center text-sm text-muted">
            {t("palette.empty")}
          </Cmdk.Empty>
          {[...groups.entries()].map(([group, list]) => (
            <Cmdk.Group
              key={group}
              heading={t(group)}
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-muted [&_[cmdk-group-heading]]:uppercase"
            >
              {list.map((command) => (
                <Cmdk.Item
                  key={command.id}
                  value={`${t(command.label)} ${command.id}`}
                  onSelect={() => {
                    setPaletteOpen(false);
                    command.run();
                  }}
                  className="flex cursor-pointer items-center justify-between rounded-md px-2 py-2 text-sm data-[selected=true]:bg-panel-2"
                >
                  <span>{t(command.label)}</span>
                  {command.shortcut && <Kbd>{formatShortcut(command.shortcut)}</Kbd>}
                </Cmdk.Item>
              ))}
            </Cmdk.Group>
          ))}
        </Cmdk.List>
      </Cmdk>
    </Dialog>
  );
}

export function CheatSheet() {
  const { t } = useTranslation();
  const { commands, cheatSheetOpen, setCheatSheetOpen } = useCommands();
  const groups = useMemo(
    () => groupCommands([...commands.values()].filter((c) => c.shortcut)),
    [commands],
  );
  return (
    <Dialog open={cheatSheetOpen} onOpenChange={setCheatSheetOpen} title={t("shortcuts.title")}>
      <div className="max-h-[60vh] space-y-4 overflow-y-auto">
        {[...groups.entries()].map(([group, list]) => (
          <section key={group}>
            <h3 className="mb-1.5 text-[11px] text-muted uppercase">{t(group)}</h3>
            <ul className="space-y-1">
              {list.map((command) => (
                <li key={command.id} className="flex items-center justify-between text-sm">
                  <span>{t(command.label)}</span>
                  <Kbd>{formatShortcut(command.shortcut!)}</Kbd>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Dialog>
  );
}
