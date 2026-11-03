import '@/styles/globals.css'
import '@/styles/instrument.css'
import '@/styles/auth.css'
import '@/styles/portfolio.css'
import '@/styles/light.css'
import '@/styles/options-chat.css'
import '@/styles/options-platform.css'
import '@/styles/market.css'
import type { AppProps } from 'next/app'
import Layout from '@/components/Layout'
import { ThemeProvider } from 'next-themes'

export default function App({ Component, pageProps }: AppProps) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark">
      <Layout><Component {...pageProps} /></Layout>
    </ThemeProvider>
  )
}
