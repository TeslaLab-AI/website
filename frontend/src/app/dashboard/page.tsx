export default function DashboardPage() {
  return (
    <div className="p-6 md:p-10 w-full max-w-5xl mx-auto">
      <h2 className="text-2xl font-bold text-zinc-900 dark:text-white mb-8">
        Repository Scan
      </h2>
      

      <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-zinc-200 dark:border-zinc-800 p-10 md:p-16 text-center flex flex-col items-center justify-center min-h-[400px]">
        <div className="w-16 h-16 bg-zinc-100 dark:bg-zinc-800 rounded-full flex items-center justify-center mb-5">
          <svg className="w-8 h-8 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.092 2.027-.269 3.012M15.15 15.15l-.09.054a13.916 13.916 0 01-5.114 2.753M12 11c0-3.517 1.009-6.799 2.753-9.571m3.44 2.04l-.054.09A13.916 13.916 0 0016 11a4 4 0 11-8 0c0-1.017.092-2.027.269-3.012" />
          </svg>
        </div>
        
        <h3 className="text-xl font-semibold text-zinc-900 dark:text-white mb-3">
          Connect GitHub to get started
        </h3>
        
        <p className="text-zinc-500 dark:text-zinc-400 max-w-md mx-auto mb-8 leading-relaxed">
          TeslaLab AI needs access to your GitHub account to list your repositories, perform automated scans, and generate maintenance fixes.
        </p>
        

        <button className="inline-flex items-center justify-center py-2.5 px-5 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors">
          Connect GitHub App
        </button>
      </div>
    </div>
  )
}
