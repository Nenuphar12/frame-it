import { Hammer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState, PageHeader } from "@/shared/ui/Misc";

export function ComingSoon({ titleKey, phase }: { titleKey: string; phase: number }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col">
      <PageHeader title={t(titleKey)} />
      <EmptyState
        icon={<Hammer size={40} />}
        title={t("comingSoon.title")}
        description={t("comingSoon.description", { phase })}
      />
    </div>
  );
}
