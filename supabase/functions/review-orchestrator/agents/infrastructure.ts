import { DomainAgent, Finding } from './domain-agent.ts'

export class InfrastructureDomainAgent extends DomainAgent {
  domain = 'infrastructure'
  relevantPrinciples = ['I-01', 'I-02', 'I-03', 'I-STD-01']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // I-01: Infrastructure Architecture
    if (!lowerText.includes('infrastructure diagram') && !lowerText.includes('network topology')) {
      findings.push({
        domain: this.domain,
        principle_id: 'I-01',
        severity: 'blocker',
        finding: 'No infrastructure architecture documented',
        recommendation: 'Provide infrastructure architecture diagram and network topology'
      })
    }
    
    // I-02: Cloud Strategy
    if (!lowerText.includes('cloud') && !lowerText.includes('aws') && !lowerText.includes('azure')) {
      findings.push({
        domain: this.domain,
        principle_id: 'I-02',
        severity: 'high',
        finding: 'Cloud platform strategy not clearly defined',
        recommendation: 'Document cloud platform choice, regions, and deployment strategy'
      })
    }
    
    // I-03: Capacity Planning
    if (!lowerText.includes('capacity') && !lowerText.includes('scalability') && !lowerText.includes('scaling')) {
      findings.push({
        domain: this.domain,
        principle_id: 'I-03',
        severity: 'high',
        finding: 'No capacity planning documented',
        recommendation: 'Define capacity requirements, scaling strategy, and resource limits'
      })
    }
    
    return findings
  }
}
