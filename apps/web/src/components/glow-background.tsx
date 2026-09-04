export function GlowBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-background" />
      <div className="bg-glow-1 absolute -left-32 top-10 h-[28rem] w-[28rem] rounded-full bg-primary/25 blur-3xl" />
      <div className="bg-glow-2 absolute -right-40 top-1/3 h-[30rem] w-[30rem] rounded-full bg-indigo-500/20 blur-3xl" />
      <div className="bg-glow-3 absolute bottom-0 left-1/3 h-[26rem] w-[26rem] rounded-full bg-primary/15 blur-3xl" />
      <div className="bg-glow-4 absolute -bottom-24 right-1/4 h-[24rem] w-[24rem] rounded-full bg-sky-400/10 blur-3xl" />
    </div>
  );
}
