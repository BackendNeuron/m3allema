// A small hook for scoped, auto-cleaned GSAP animations.

import gsap from "gsap";
import { type DependencyList, useLayoutEffect, useRef } from "react";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Run `animate` after render whenever `deps` change. Animations are scoped to the
 * returned ref's element and reverted on cleanup, so React and GSAP never fight
 * over the same DOM. Skipped entirely when the user prefers reduced motion.
 */
export function useGSAP<T extends Element>(
  animate: (g: typeof gsap, root: T) => void,
  deps: DependencyList,
) {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root || reducedMotion()) return;
    const context = gsap.context(() => animate(gsap, root), root);
    return () => context.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

export { gsap };
