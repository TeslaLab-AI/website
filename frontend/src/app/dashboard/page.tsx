'use client'

export default function DashboardPage() {
  return (
    <div className="flex flex-col min-h-screen items-center justify-center bg-zinc-50 dark:bg-black p-4 font-sans">
      <main className="w-full max-w-2xl bg-white dark:bg-zinc-900 rounded-2xl shadow-xl p-8 border border-zinc-200 dark:border-zinc-800">
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-white mb-2">Dashboard</h1>
        <p className="text-zinc-500 dark:text-zinc-400">
          Welcome to the TeslaLab AI dashboard. You are successfully logged in.
        </p>
      </main>
    </div>
  )
}
