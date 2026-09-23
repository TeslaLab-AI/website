'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { saveOnboardingUserType } from '@/app/actions/auth'
import { Rocket, Briefcase, Code2, Layers, Check, ArrowRight } from 'lucide-react'

export type UserTypeOption = 'startup' | 'agency' | 'freelancer' | 'others'

interface OnboardingOption {
  id: UserTypeOption
  label: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const ONBOARDING_OPTIONS: OnboardingOption[] = [
  {
    id: 'startup',
    label: 'Startup',
    description: 'Fast-moving team building innovative products.',
    icon: Rocket,
  },
  {
    id: 'agency',
    label: 'Agency',
    description: 'Managing and maintaining codebases for multiple clients.',
    icon: Briefcase,
  },
  {
    id: 'freelancer',
    label: 'Freelancer',
    description: 'Independent engineer delivering custom solutions.',
    icon: Code2,
  },
  {
    id: 'others',
    label: 'Others',
    description: 'Individual developer, educator, or open-source maintainer.',
    icon: Layers,
  },
]

interface OnboardingScreenProps {
  onCompleted?: () => void
}

export function OnboardingScreen({ onCompleted }: OnboardingScreenProps) {
  const router = useRouter()
  const [selectedType, setSelectedType] = useState<UserTypeOption | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleContinue() {
    if (!selectedType) {
      setError('Please select an option to continue.')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const result = await saveOnboardingUserType(selectedType)
      if (result.error) {
        setError(result.error)
        setLoading(false)
      } else {
        if (onCompleted) {
          onCompleted()
        } else {
          router.refresh()
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('An error occurred while saving your selection.')
      }
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[75vh] px-4 py-8 w-full max-w-3xl mx-auto font-sans">
      <div className="w-full bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-zinc-200 dark:border-zinc-800 p-8 sm:p-12">
        {/* Header Section */}
        <div className="text-center max-w-xl mx-auto mb-10">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 mb-4">
            <Rocket className="w-6 h-6" />
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-zinc-900 dark:text-white tracking-tight mb-3">
            What best describes you?
          </h1>
          <p className="text-base text-zinc-500 dark:text-zinc-400 leading-relaxed">
            Help us tailor your TeslaLab workspace.
          </p>
        </div>

        {/* Error Notification */}
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Option Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-10">
          {ONBOARDING_OPTIONS.map((option) => {
            const Icon = option.icon
            const isSelected = selectedType === option.id

            return (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  setSelectedType(option.id)
                  setError(null)
                }}
                className={`relative flex flex-col p-6 text-left rounded-xl border-2 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-zinc-900 ${
                  isSelected
                    ? 'border-blue-600 dark:border-blue-500 bg-blue-50/50 dark:bg-blue-950/30 shadow-md scale-[1.01]'
                    : 'border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/50 hover:border-zinc-300 dark:hover:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-850'
                }`}
              >
                {/* Top Row: Icon & Checkmark indicator */}
                <div className="flex items-center justify-between w-full mb-4">
                  <div
                    className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${
                      isSelected
                        ? 'bg-blue-600 text-white'
                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                  </div>

                  {isSelected && (
                    <div className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center">
                      <Check className="w-4 h-4 stroke-[3]" />
                    </div>
                  )}
                </div>

                {/* Content */}
                <h3
                  className={`text-lg font-semibold mb-1 ${
                    isSelected ? 'text-blue-950 dark:text-white' : 'text-zinc-900 dark:text-white'
                  }`}
                >
                  {option.label}
                </h3>
                <p className="text-xs sm:text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  {option.description}
                </p>
              </button>
            )
          })}
        </div>

        {/* Action Button */}
        <div className="flex items-center justify-end">
          <button
            type="button"
            disabled={!selectedType || loading}
            onClick={handleContinue}
            className="w-full sm:w-auto inline-flex items-center justify-center py-3 px-8 rounded-xl text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 active:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm"
          >
            {loading ? (
              'Saving...'
            ) : (
              <>
                Continue
                <ArrowRight className="w-4 h-4 ml-2" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
