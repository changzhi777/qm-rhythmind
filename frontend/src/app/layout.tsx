import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Toast } from "@/components/ui/toast";

const inter = Inter({
  variable: "--font-geist-sans",
  subsets: ["latin"],
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