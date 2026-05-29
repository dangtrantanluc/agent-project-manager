import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useEffect, useState } from "react";
import { I18nextProvider } from "react-i18next";
import { Toaster } from "sonner";
import i18n from "@/i18n/i18n";
import { useAuth } from "@/features/auth/store";

export function Providers({ children }: { children: ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, staleTime: 30_000 },
        },
      }),
  );
  const userLang = useAuth((s) => s.user?.lang);
  useEffect(() => {
    if (userLang && userLang !== i18n.language) {
      i18n.changeLanguage(userLang);
    }
  }, [userLang]);
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>
        <Toaster position="top-right" richColors closeButton />
        {children}
      </QueryClientProvider>
    </I18nextProvider>
  );
}
