import { DomainAgent, Finding } from './domain-agent.ts'

export class ApplicationDomainAgent extends DomainAgent {
  domain = 'application'
  relevantPrinciples = ['A-01', 'A-02', 'A-03', 'A-STD-01', 'A-STD-02']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // A-01: Architecture Diagram
    if (!lowerText.includes('architecture diagram') && !lowerText.includes('hld')) {
      findings.push({
        domain: this.domain,
        principle_id: 'A-01',
        severity: 'blocker',
        finding: 'No application architecture diagram documented',
        recommendation: 'Provide High Level Design (HLD) and application architecture diagrams'
      })
    }
    
    // A-02: Technology Stack
    if (!lowerText.includes('technology stack') && !lowerText.includes('tech stack')) {
      findings.push({
        domain: this.domain,
        principle_id: 'A-02',
        severity: 'high',
        finding: 'Technology stack not clearly defined',
        recommendation: 'Document complete technology stack with versions and rationale'
      })
    }
    
    // A-03: Architecture Decision Records
    if (!lowerText.includes('adr') && !lowerText.includes('architecture decision')) {
      findings.push({
        domain: this.domain,
        principle_id: 'A-03',
        severity: 'medium',
        finding: 'No Architecture Decision Records documented',
        recommendation: 'Create ADRs for key architectural decisions'
      })
    }
    
    return findings
  }
}
