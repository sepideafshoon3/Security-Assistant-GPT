import { useState } from "react";

type TimeBand = "morning" | "afternoon" | "evening" | "night";
type GreetingLine = { title: string; subtitle: string };

const GREETINGS: Record<TimeBand, GreetingLine[]> = {
  morning: [
    { title: "Good morning ☀️", subtitle: "What are we breaking today?" },
    { title: "Morning, dev", subtitle: "Coffee's brewing — so is the next finding." },
    { title: "Rise and grep", subtitle: "Let's see what yesterday's build left behind." },
  ],
  afternoon: [
    { title: "Good afternoon", subtitle: "Mid-day check — any weird logs yet?" },
    { title: "Hey", subtitle: "Let's find something worth patching." },
    { title: "Afternoon", subtitle: "Paste a repo, a diff, or just say hi." },
  ],
  evening: [
    { title: "Good evening", subtitle: "Wrapping up, or just getting started?" },
    { title: "Evening", subtitle: "Prime time for \"just one more commit.\"" },
    { title: "Hey there", subtitle: "What's on the review queue tonight?" },
  ],
  night: [
    { title: "Late-night vibe coding? 🌙", subtitle: "Respect. What are we hunting for?" },
    { title: "Found a bug at 2am?", subtitle: "Classic. Let's squash it together." },
    { title: "Still up?", subtitle: "The best findings show up after midnight." },
    { title: "3am and debugging", subtitle: "A tale as old as time. What's broken?" },
  ],
};

function getTimeBand(hour: number): TimeBand {
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 17) return "afternoon";
  if (hour >= 17 && hour < 22) return "evening";
  return "night";
}

function pickGreeting(): GreetingLine {
  const band = getTimeBand(new Date().getHours());
  const pool = GREETINGS[band];
  return pool[Math.floor(Math.random() * pool.length)];
}

export function Greeting() {
  const [greeting] = useState(pickGreeting);
  return (
    <div className="text-center max-w-md mb-6 motion-safe:animate-in motion-safe:fade-in duration-500">
      <h2 className="text-2xl text-fg-primary mb-2">{greeting.title}</h2>
      <p className="text-fg-tertiary">{greeting.subtitle}</p>
    </div>
  );
}
