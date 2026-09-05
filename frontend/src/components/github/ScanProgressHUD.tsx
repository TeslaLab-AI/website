"use client";

import React, { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Circle, Loader2, ShieldAlert, FileText, Database, Activity } from "lucide-react";
import { createClient } from "@/utils/supabase/client";

interface LogEntry {
  timestamp: string;
  message: string;
}

export interface ScanProgressState {
  phase: "initializing" | "ingesting" | "analyzing" | "finalizing" | "completed" | "failed" | "unknown";
  progress: number;
  logs: LogEntry[];
}

interface ScanProgressHUDProps {
  scanId: string;
  onComplete: () => void;
}

const PHASES = [
  { id: "initializing", label: "Initialization", icon: Activity },
  { id: "ingesting", label: "Data Ingestion", icon: Database },
  { id: "analyzing", label: "Security & AI Analysis", icon: ShieldAlert },
  { id: "finalizing", label: "Finalization", icon: FileText },
];

export function ScanProgressHUD({ scanId, onComplete }: ScanProgressHUDProps) {
  const [progressState, setProgressState] = useState<ScanProgressState>({
    phase: "initializing",
    progress: 0,
    logs: [],
  });
  
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Auto-scroll terminal to bottom
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [progressState.logs]);

  useEffect(() => {
    let intervalId: NodeJS.Timeout;
    let isCompleted = false;
    
    const fetchProgress = async () => {
      if (isCompleted) return;
      try {
        const supabase = createClient();
        const { data: { session } } = await supabase.auth.getSession();
        const token = session?.access_token;
        if (!token) return;

        const res = await fetch(`/api/github/scan/${scanId}/progress`, {
          headers: {
            "Authorization": `Bearer ${token}`
          }
        });
        
        if (res.ok) {
          const data: ScanProgressState = await res.json();
          setProgressState(data);
          
          if (data.phase === "completed" || data.phase === "failed") {
            isCompleted = true;
            clearInterval(intervalId);
            // Wait a brief moment before triggering completion to let the user see the 100% state
            setTimeout(onComplete, 2500);
          }
        }
      } catch (err) {
        console.error("Failed to fetch scan progress:", err);
      }
    };

    // Initial fetch
    fetchProgress();
    // Poll every 500ms for that high-frequency real-time feel
    intervalId = setInterval(fetchProgress, 500);
    
    return () => clearInterval(intervalId);
  }, [scanId, onComplete]);

  // Determine current phase index
  const currentPhaseIndex = PHASES.findIndex(p => p.id === progressState.phase);
  const safePhaseIndex = currentPhaseIndex === -1 ? (progressState.phase === 'completed' ? 4 : 0) : currentPhaseIndex;

  return (
    <div className="w-full flex flex-col items-center justify-center min-h-[500px] p-8 rounded-3xl bg-gray-950/80 border border-white/5 backdrop-blur-xl relative overflow-hidden shadow-2xl">
      {/* Background Ambient Glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-blue-500/10 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-purple-500/10 rounded-full blur-[80px] pointer-events-none" />

      {/* Top Section: Radar / Circle Progress */}
      <div className="relative flex items-center justify-center mb-12">
        {/* Outer rotating dashed ring */}
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
          className="absolute inset-[-40px] rounded-full border border-dashed border-white/20 w-48 h-48"
        />
        {/* Inner solid ring */}
        <div className="absolute inset-[-20px] rounded-full border border-white/10 w-36 h-36" />
        
        {/* Core display */}
        <div className="relative z-10 w-28 h-28 bg-black/50 border border-white/20 rounded-full flex flex-col items-center justify-center shadow-[0_0_40px_rgba(59,130,246,0.3)] backdrop-blur-md">
          {progressState.phase === "failed" ? (
            <ShieldAlert className="text-red-500 w-10 h-10 mb-1" />
          ) : progressState.phase === "completed" ? (
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: "spring", bounce: 0.5 }}
            >
              <CheckCircle2 className="text-emerald-400 w-10 h-10 mb-1" />
            </motion.div>
          ) : (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
            >
              <Loader2 className="text-blue-400 w-10 h-10 mb-1" />
            </motion.div>
          )}
          <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
            {progressState.progress}%
          </span>
        </div>
      </div>

      {/* Middle Section: Pipeline Stepper */}
      <div className="w-full max-w-2xl flex items-center justify-between relative mb-10 z-10">
        <div className="absolute left-0 right-0 top-1/2 h-[2px] bg-white/10 -translate-y-1/2 z-0" />
        <motion.div 
          className="absolute left-0 top-1/2 h-[2px] bg-gradient-to-r from-blue-500 to-purple-500 -translate-y-1/2 z-0"
          initial={{ width: "0%" }}
          animate={{ width: `${(safePhaseIndex / (PHASES.length - 1)) * 100}%` }}
          transition={{ duration: 0.5, ease: "easeInOut" }}
        />
        
        {PHASES.map((phase, index) => {
          const isActive = index === safePhaseIndex;
          const isCompleted = index < safePhaseIndex || progressState.phase === "completed";
          const Icon = phase.icon;
          
          return (
            <div key={phase.id} className="relative z-10 flex flex-col items-center gap-3">
              <motion.div 
                className={`w-12 h-12 rounded-full flex items-center justify-center border-2 backdrop-blur-md transition-colors duration-300 ${
                  isCompleted 
                    ? "bg-blue-500/20 border-blue-400 text-blue-400" 
                    : isActive
                    ? "bg-purple-500/30 border-purple-400 text-purple-300 shadow-[0_0_20px_rgba(168,85,247,0.4)]"
                    : "bg-gray-900 border-white/10 text-gray-500"
                }`}
                whileHover={{ scale: 1.1 }}
                animate={isActive ? { y: [0, -5, 0] } : {}}
                transition={isActive ? { duration: 2, repeat: Infinity } : {}}
              >
                {isCompleted ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-5 h-5" />}
              </motion.div>
              <span className={`text-xs font-semibold tracking-wider uppercase transition-colors duration-300 ${
                isActive ? "text-purple-300" : isCompleted ? "text-blue-400" : "text-gray-500"
              }`}>
                {phase.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Bottom Section: Live Terminal logs */}
      <div className="w-full max-w-3xl bg-black/60 border border-white/10 rounded-xl overflow-hidden backdrop-blur-xl shadow-2xl relative z-10">
        {/* Terminal Header */}
        <div className="flex items-center px-4 py-2 bg-white/[0.03] border-b border-white/10">
          <div className="flex gap-2 mr-4">
            <div className="w-3 h-3 rounded-full bg-red-500/50" />
            <div className="w-3 h-3 rounded-full bg-yellow-500/50" />
            <div className="w-3 h-3 rounded-full bg-green-500/50" />
          </div>
          <span className="text-xs text-gray-400 font-mono">scan-execution-logs.sh</span>
        </div>
        
        {/* Terminal Body */}
        <div 
          ref={terminalRef}
          className="p-4 h-48 overflow-y-auto font-mono text-sm space-y-1.5 scroll-smooth custom-scrollbar"
        >
          <AnimatePresence initial={false}>
            {progressState.logs.map((log, i) => (
              <motion.div 
                key={log.timestamp + i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex gap-4"
              >
                <span className="text-gray-600 shrink-0">
                  [{new Date(log.timestamp).toISOString().substring(11, 23)}]
                </span>
                <span className={`${
                  log.message.includes("Error") ? "text-red-400" : 
                  log.message.includes("completed") ? "text-emerald-400" : 
                  "text-blue-300"
                }`}>
                  {log.message}
                </span>
              </motion.div>
            ))}
          </AnimatePresence>
          {progressState.phase !== "completed" && progressState.phase !== "failed" && (
            <div className="flex gap-4 mt-2">
              <span className="text-gray-600 shrink-0">[{new Date().toISOString().substring(11, 23)}]</span>
              <span className="text-purple-400 animate-pulse">_</span>
            </div>
          )}
        </div>
      </div>
      
      {/* Inline styles for custom scrollbar to keep it self-contained */}
      <style dangerouslySetInnerHTML={{__html: `
        .custom-scrollbar::-webkit-scrollbar {
          width: 8px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.02);
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.2);
        }
      `}} />
    </div>
  );
}
