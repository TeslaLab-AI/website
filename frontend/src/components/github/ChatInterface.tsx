'use client'

import { useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import ReactMarkdown from 'react-markdown'

export function ChatInterface({ repoId }: { repoId: string }) {
  const [messages, setMessages] = useState<{role: 'user' | 'assistant', content: string, references?: any[]}[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const supabase = createClient()

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setIsLoading(true)

    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error("Not authenticated")

      const res = await fetch('/api/github/chat', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          repository_id: repoId,
          message: userMessage
        })
      })

      if (!res.ok) {
        throw new Error("Failed to get response")
      }

      const data = await res.json()
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: data.reply,
        references: data.references 
      }])
    } catch (err) {
      console.error(err)
      setMessages(prev => [...prev, { role: 'assistant', content: "Sorry, I encountered an error answering that question." }])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-[500px]">
      <div className="flex-1 overflow-y-auto mb-4 space-y-4 pr-2">
        {messages.length === 0 && (
          <div className="text-center text-zinc-500 dark:text-zinc-400 mt-10">
            Ask me anything about your codebase! Try:<br/>
            <span className="italic">"Where is the authentication logic?"</span> or <span className="italic">"Explain how the dashboard works."</span>
          </div>
        )}
        
        {messages.map((msg, i) => (
          <div key={i} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${
              msg.role === 'user' 
                ? 'bg-blue-600 text-white' 
                : 'bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100'
            }`}>
              {msg.role === 'user' ? (
                <div>{msg.content}</div>
              ) : (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              )}
            </div>
            
            {msg.references && msg.references.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 max-w-[85%]">
                <span className="text-xs text-zinc-500 font-medium my-auto">References:</span>
                {msg.references.map((ref: any, idx: number) => (
                  <span key={idx} className="text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 font-mono">
                    {ref.file_path}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {isLoading && (
          <div className="flex items-start">
            <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-2xl px-4 py-3 flex items-center space-x-2">
              <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce"></div>
              <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{animationDelay: "0.2s"}}></div>
              <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{animationDelay: "0.4s"}}></div>
            </div>
          </div>
        )}
      </div>

      <form onSubmit={sendMessage} className="mt-auto relative">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about the codebase..."
          className="w-full bg-white dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 rounded-xl pl-4 pr-12 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 text-zinc-900 dark:text-zinc-100 shadow-sm"
          disabled={isLoading}
        />
        <button 
          type="submit"
          disabled={isLoading || !input.trim()}
          className="absolute right-2 top-2 p-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        </button>
      </form>
    </div>
  )
}
