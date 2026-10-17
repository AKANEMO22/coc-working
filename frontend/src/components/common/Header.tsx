"use client";

import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";
import { useState } from "react";
import { Menu, X } from "lucide-react";

export function Header() {
  const [mobileOpen, setMobileOpen] = useState(false);

  const navLinks = [
    { href: "/interview", label: "Phòng Phỏng vấn" },
    ...(process.env.NODE_ENV === "development" ? [{ href: "/debug", label: "Debug luồng" }] : []),
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border-color)] bg-[var(--glass-bg)] backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/interview" className="flex items-center gap-2 group">
            <span className="text-2xl">🐸</span>
            <span className="text-lg font-bold gradient-text hidden sm:inline">
              Cóc Đi Làm
            </span>
          </Link>

          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="px-4 py-2 rounded-lg text-sm font-medium text-[var(--text-secondary)]
                  hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]
                  transition-all duration-200"
              >
                {link.label}
              </Link>
            ))}
          </nav>

          {/* Right side */}
          <div className="flex items-center gap-3">
            <ThemeToggle />

            {/* Mobile menu button */}
            <button
              className="md:hidden p-2 rounded-lg hover:bg-[var(--bg-secondary)] transition-colors"
              onClick={() => setMobileOpen(!mobileOpen)}
            >
              {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* Mobile Nav */}
        {mobileOpen && (
          <nav className="md:hidden py-4 border-t border-[var(--border-color)]">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="block px-4 py-3 rounded-lg text-sm font-medium text-[var(--text-secondary)]
                  hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]
                  transition-all duration-200"
                onClick={() => setMobileOpen(false)}
              >
                {link.label}
              </Link>
            ))}
          </nav>
        )}
      </div>
    </header>
  );
}
