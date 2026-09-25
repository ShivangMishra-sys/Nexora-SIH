import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const metadata: Metadata = {
  title: 'UrbanFlow — Urban Flood Nowcasting & Safe-Routing | Nexora SIH 2026',
  description:
    'Real-time urban flood prediction and flood-safe routing for Chennai, India. ' +
    'Couples rainfall nowcasting, surface runoff, and drainage network modelling. ' +
    'SIH 2026 | PS ID 26085 | Theme: Disaster Management',
  keywords: ['urban flooding', 'flood nowcasting', 'safe routing', 'Chennai', 'disaster management', 'SIH 2026'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌊</text></svg>" />
      </head>
      <body className="bg-navy text-white antialiased overflow-hidden">
        {children}
      </body>
    </html>
  );
}
