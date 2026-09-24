// "Save as style" / "Save as layout" from the artwork being edited (docs/templates.md §3).
//
// The server reads the *saved* document, so the dialog first waits for the editor's autosave to
// land: saving a template from a document the server has not seen yet would store the look the
// artwork had a few keystrokes ago.
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useSaveAsTemplate, type TemplateKind } from "@/api/queries";
import { save as saveDocument } from "@/editor/store";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";
import { problemMessage } from "@/shared/problem";

export function SaveAsTemplateDialog({
  kind,
  artworkId,
  suggestedName,
  onClose,
}: {
  kind: TemplateKind;
  artworkId: string;
  suggestedName: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const save = useSaveAsTemplate();
  const [name, setName] = useState(suggestedName);
  const [saved, setSaved] = useState(false);
  const submitRef = useRef<HTMLButtonElement>(null);

  const submit = async () => {
    await saveDocument();
    save.mutate({ kind, artworkId, name: name.trim() }, { onSuccess: () => setSaved(true) });
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={t(
        kind === "frame_style" ? "templates.saveAsStyleTitle" : "templates.saveAsLayoutTitle",
      )}
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        submitRef.current?.focus();
      }}
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          {t("templates.name")}
          <input
            className="h-8 rounded-md border border-border bg-bg px-2 text-sm"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setSaved(false);
            }}
            required
          />
        </label>
        {save.error && (
          <p className="text-sm text-danger">
            {problemMessage(t, save.error)}
          </p>
        )}
        {saved && <p className="text-sm text-accent">{t("templates.saved")}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {saved ? t("common.close") : t("common.cancel")}
          </Button>
          <Button
            ref={submitRef}
            type="submit"
            variant="primary"
            disabled={save.isPending || !name.trim()}
          >
            {save.isPending && <Spinner size={14} />}
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
