import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], display: 'swap', variable: '--font-inter' });
const jetbrainsMono = JetBrains_Mono({ subsets: ['latin'], display: 'swap', variable: '--font-jetbrains' });

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
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        <link
          rel="icon"
          href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌊</text></svg>"
        />
      </head>
      <body style={{ margin: 0, padding: 0, background: '#080d1a', overflow: 'hidden' }}>
        {children}
      </body>
    </html>
  );
}
