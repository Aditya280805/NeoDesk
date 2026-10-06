import '@/styles/globals.css'
import '@/styles/instrument.css'
import type { AppProps } from 'next/app'
import Layout from '@/components/Layout'
import { useEffect } from 'react'
import { wsService } from '@/services/ws'
import { ThemeProvider } from 'next-themes'

export default function App({ Component, pageProps }: AppProps) {
  useEffect(() => {
    wsService.connect()
    return () => wsService.disconnect()
  }, [])
  
  return (
    <ThemeProvider attribute="class" defaultTheme="dark">
      <Layout><Component {...pageProps} /></Layout>
    </ThemeProvider>
  )
}
