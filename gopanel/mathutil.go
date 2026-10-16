package main

import "math"

func clamp(v, lo, hi float64) float64 { return math.Min(hi, math.Max(lo, v)) }
func clamp01(v float64) float64       { return clamp(v, 0, 1) }
func abs(v float64) float64           { return math.Abs(v) }
func hypot(a, b float64) float64      { return math.Hypot(a, b) }
func maxf(a, b float64) float64       { return math.Max(a, b) }
func minf(a, b float64) float64       { return math.Min(a, b) }
