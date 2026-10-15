import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TelemetryAnalysisPanel } from './TelemetryAnalysisPanel';

describe('TelemetryAnalysisPanel', () => {
  it('can be closed and reopened without losing the analysis action', () => {
    render(<TelemetryAnalysisPanel analysis={null} loading={false} error={null} onAnalyze={vi.fn()} available={false} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close trend and excursion analysis' }));
    expect(screen.getByRole('button', { name: 'Show trend & excursion analysis' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Trend & excursion analysis' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show trend & excursion analysis' }));
    expect(screen.getByRole('heading', { name: 'Trend & excursion analysis' })).toBeInTheDocument();
  });
});
