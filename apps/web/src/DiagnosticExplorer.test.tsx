import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DiagnosticExplorer } from './DiagnosticExplorer';

describe('DiagnosticExplorer', () => {
  it('shows a primary measurement when no metric is selected and there are no findings', () => {
    render(<DiagnosticExplorer
      assessment={null}
      telemetry={null}
      readings={[]}
      scenario={null}
      freshness="Unavailable"
      selectedMetric={null}
      selectedAlert={null}
      onSelectMetric={() => undefined}
      diagnosis={null}
      diagnosisLoading={false}
      diagnosisError={null}
      providerStatus={null}
      diagnosticAvailable={false}
      onRequestDiagnosis={() => undefined}
      api={{}}
      pumpId={null}
    />);

    expect(screen.getByRole('heading', { name: 'Vibration' })).toBeInTheDocument();
    expect(screen.getByText('No valid samples are available for this measurement.')).toBeInTheDocument();
  });
});
