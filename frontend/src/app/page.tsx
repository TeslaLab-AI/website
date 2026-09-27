/**
 * Purpose:
 * Renders the TeslaLab landing page.
 *
 * Responsibilities:
 * - Communicates the core TeslaLab product value.
 * - Provides navigation and primary calls to action.
 */

import { Capabilities } from "@/components/landing/Capabilities";
import { FinalCta } from "@/components/landing/FinalCta";
import { Footer } from "@/components/landing/Footer";
import { Header } from "@/components/landing/Header";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { MaintenanceEngineer } from "@/components/landing/MaintenanceEngineer";
import { ProductFlow } from "@/components/landing/ProductFlow";
import { Safety } from "@/components/landing/Safety";

export default function HomePage() {
  return (
    <div className="tl-landing relative flex flex-1 flex-col overflow-x-hidden">
      <div className="tl-atmosphere" aria-hidden="true" />
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-[var(--tl-signal)] focus:px-3 focus:py-2 focus:text-sm focus:text-[#1a0906]"
      >
        Skip to content
      </a>
      <Header />
      <main id="main" className="relative z-[1]">
        <Hero />
        <MaintenanceEngineer />
        <ProductFlow />
        <Capabilities />
        <HowItWorks />
        <Safety />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
