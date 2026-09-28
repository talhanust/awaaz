import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Awaaz — civic accountability',
  description: 'Your complaint doesn’t end when you file it. It ends when it’s fixed.',
};
export const viewport: Viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link href="https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,700&family=Noto+Sans:wght@400;600&family=Noto+Nastaliq+Urdu&display=swap" rel="stylesheet" />
      </head>
      <body>
        <header className="top">
          <b>Awaaz</b>
          <nav><a href="/dashboard">Authority queue</a><a href="/reports">Neighborhood reports</a></nav>
        </header>
        {children}
      </body>
    </html>
  );
}
