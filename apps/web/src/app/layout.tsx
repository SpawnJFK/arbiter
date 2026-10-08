import { getI18n } from "@/lib/i18n/server";
import type { Metadata, Viewport } from "next";
import { ToastProvider } from "@/components/ui/toast";
import { I18nProvider } from "@/lib/i18n/client";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return {
    title: { default: "Arbiter", template: "%s · Arbiter" },
    description: t("layout.metaDescription"),
  };
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f6f7" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0e11" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const { t, locale, locales, overrides } = await getI18n();
  return (
    <html lang={locale} className="h-full">
      <body className="min-h-full">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop"
        >
          {t("layout.skipToContent")}
        </a>
        <I18nProvider locale={locale} locales={locales} overrides={overrides}>
          <ToastProvider>{children}</ToastProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
