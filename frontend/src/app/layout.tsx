import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/common/ThemeProvider";
import { Header } from "@/components/common/Header";

const inter = Inter({
  subsets: ["latin", "vietnamese"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Cóc Đi Làm — Phòng Lab Phỏng Vấn OJT Thực Chiến",
  description:
    "Hệ thống AI đồng hành từ tối ưu CV đến phỏng vấn 1-1 bằng giọng nói thời gian thực. Giúp sinh viên FPT tự tin trước phỏng vấn OJT.",
  keywords: ["phỏng vấn OJT", "CV", "FPT", "interview practice", "AI voice interview"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`} suppressHydrationWarning>
        <ThemeProvider>
          <div className="min-h-screen flex flex-col" suppressHydrationWarning>
            <Header />
            <main className="flex-1" suppressHydrationWarning>{children}</main>
            <footer className="border-t border-[var(--border-color)] py-6 text-center text-sm text-[var(--text-muted)]" suppressHydrationWarning>
              <p>🐸 Cóc Đi Làm — Nhóm 1, ĐH FPT © 2026</p>
            </footer>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
