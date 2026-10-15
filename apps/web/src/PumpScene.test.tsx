import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { calculateEngineeringMetrics } from './engineering';
import { PumpScene } from './PumpScene';

describe('pump scene fallback', () => {
  it('keeps controls and scenario information available when WebGL creation fails', async () => {
    render(<PumpScene scenario="cavitation" telemetry={null} metrics={calculateEngineeringMetrics({})} playing rendererFactory={() => { throw new Error('WebGL unavailable'); }} resetToken={0} />);
    expect(await screen.findByText('3D view unavailable')).toBeInTheDocument();
    expect(screen.getByText(/SIMULATION RESPONSE.*CAVITATION/)).toBeInTheDocument();
    expect(document.querySelector('[aria-label="Pump component labels"]')).not.toBeNull();
  });
});
