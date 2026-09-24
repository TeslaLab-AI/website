'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { saveOnboardingUserType } from '@/app/actions/auth'
import { Rocket, Briefcase, Code2, Layers, ArrowRight, type LucideProps } from 'lucide-react'

export type UserTypeOption = 'startup' | 'agency' | 'freelancer' | 'others'

interface OnboardingOption {
  id: UserTypeOption
  label: string
  description: string
  icon: React.ComponentType<LucideProps>
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
    description: 'Managing codebases for multiple clients.',
    icon: Briefcase,
  },
  {
    id: 'freelancer',
    label: 'Freelancer',
    description: 'Independent engineer delivering solutions.',
    icon: Code2,
  },
  {
    id: 'others',
    label: 'Other',
    description: 'Developer, educator, or OSS maintainer.',
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
    <div className="tl-landing flex flex-col items-center justify-center min-h-[80vh] px-4 py-12 w-full relative overflow-hidden">
      {/* Atmospheric Background Glow */}
      <div className="tl-atmosphere" />

      {/* Content */}
      <div className="relative z-10 w-full max-w-5xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <p className="tl-kicker mb-4">Get Started</p>
          <h1
            className="text-3xl sm:text-4xl font-bold tracking-tight mb-3"
            style={{ color: 'var(--tl-fg)' }}
          >
            What best describes you?
          </h1>
          <p
            className="text-base sm:text-lg leading-relaxed max-w-md mx-auto"
            style={{ color: 'var(--tl-muted)' }}
          >
            Help us tailor your TeslaLab workspace.
          </p>
        </div>

        {/* Error */}
        {error && (
          <div
            className="mb-8 mx-auto max-w-lg p-4 rounded-xl text-sm text-center"
            style={{
              background: 'rgba(255, 94, 58, 0.1)',
              border: '1px solid rgba(255, 94, 58, 0.25)',
              color: '#ff7a5c',
            }}
          >
            {error}
          </div>
        )}

        {/* Option Cards — 4 across on desktop */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-12">
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
                className="group relative flex flex-col items-center text-center rounded-2xl p-8 focus:outline-none"
                style={{
                  background: isSelected
                    ? 'rgba(255, 94, 58, 0.08)'
                    : 'rgba(243, 238, 228, 0.03)',
                  border: isSelected
                    ? '1.5px solid rgba(255, 94, 58, 0.45)'
                    : '1px solid rgba(243, 238, 228, 0.08)',
                  backdropFilter: 'blur(16px)',
                  WebkitBackdropFilter: 'blur(16px)',
                  boxShadow: isSelected
                    ? '0 0 32px rgba(255, 94, 58, 0.12), 0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(243,238,228,0.06)'
                    : '0 4px 24px rgba(0,0,0,0.2), inset 0 1px 0 rgba(243,238,228,0.04)',
                  transition: 'all 280ms cubic-bezier(0.22, 1, 0.36, 1)',
                  transform: isSelected ? 'scale(1.03)' : 'scale(1)',
                  cursor: 'pointer',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    const el = e.currentTarget
                    el.style.transform = 'scale(1.04)'
                    el.style.boxShadow =
                      '0 0 28px rgba(255, 94, 58, 0.1), 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(243,238,228,0.08)'
                    el.style.borderColor = 'rgba(243, 238, 228, 0.2)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    const el = e.currentTarget
                    el.style.transform = 'scale(1)'
                    el.style.boxShadow =
                      '0 4px 24px rgba(0,0,0,0.2), inset 0 1px 0 rgba(243,238,228,0.04)'
                    el.style.borderColor = 'rgba(243, 238, 228, 0.08)'
                  }
                }}
              >
                {/* Icon */}
                <div
                  className="w-14 h-14 rounded-xl flex items-center justify-center mb-5"
                  style={{
                    background: isSelected
                      ? 'rgba(255, 94, 58, 0.15)'
                      : 'rgba(243, 238, 228, 0.06)',
                    border: isSelected
                      ? '1px solid rgba(255, 94, 58, 0.3)'
                      : '1px solid rgba(243, 238, 228, 0.08)',
                    transition: 'all 280ms cubic-bezier(0.22, 1, 0.36, 1)',
                  }}
                >
                  <Icon
                    className="w-6 h-6 transition-colors duration-300"
                    color={isSelected ? '#ff5e3a' : '#9b9589'}
                  />
                </div>

                {/* Label */}
                <h3
                  className="text-lg font-semibold mb-2 tracking-tight"
                  style={{
                    color: isSelected ? '#ff5e3a' : 'var(--tl-fg)',
                    transition: 'color 280ms ease',
                  }}
                >
                  {option.label}
                </h3>

                {/* Description */}
                <p
                  className="text-xs leading-relaxed"
                  style={{
                    color: 'var(--tl-muted)',
                  }}
                >
                  {option.description}
                </p>

                {/* Selected Ring Indicator */}
                {isSelected && (
                  <div
                    className="absolute -top-px -left-px -right-px -bottom-px rounded-2xl pointer-events-none"
                    style={{
                      boxShadow: '0 0 24px rgba(255, 94, 58, 0.15)',
                    }}
                  />
                )}
              </button>
            )
          })}
        </div>

        {/* Continue Button */}
        <div className="flex justify-center">
          <button
            type="button"
            disabled={!selectedType || loading}
            onClick={handleContinue}
            className="tl-btn-primary rounded-xl px-10 py-3 text-sm font-semibold tracking-wide disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              minWidth: '200px',
              borderRadius: '0.75rem',
              transition: 'all 200ms ease',
            }}
          >
            {loading ? (
              'Saving...'
            ) : (
              <span className="inline-flex items-center gap-2">
                Continue
                <ArrowRight className="w-4 h-4" />
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
