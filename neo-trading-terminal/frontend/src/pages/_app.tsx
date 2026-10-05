import '@/styles/globals.css'
import type { AppProps } from 'next/app'
import Layout from '@/components/Layout'
import { useEffect } from 'react'
import { wsService } from '@/services/ws'

export default function App({ Component, pageProps }: AppProps) {
  useEffect(() => {
    wsService.connect()
    return () => wsService.disconnect()
  }, [])
  
  return <Layout><Component {...pageProps} /></Layout>
}
