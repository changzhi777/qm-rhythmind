import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Toast } from "@/components/ui/toast";

const inter = localFont({
  variable: "--font-geist-sans",
  src: [
    { path: "../../public/fonts/Inter-Regular.woff2", weight: "400" },
    { path: "../../public/fonts/Inter-Bold.woff2", weight: "700" },
  ],
  display: "swap",
  fallback: ["system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  title: "RHYTHMIND 律动 — 健康数据仪表盘",
  description: "多智能体 AI 健康管理平台，数据大屏与 AI 健康报告",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="dark">
      <body className={`${inter.variable} min-h-full flex flex-col antialiased`}>
        {children}
        <Toast />
      </body>
    </html>
  );
}