import { DomainAgent, Finding } from './domain-agent.ts'

export class IntegrationDomainAgent extends DomainAgent {
  domain = 'integration'
  relevantPrinciples = ['I-01', 'I-02', 'I-03', 'I-STD-01']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // I-01: API-First Design
    if (!lowerText.includes('api') && !lowerText.includes('rest') && !lowerText.includes('graphql')) {
      findings.push({
        domain: this.domain,
        principle_id: 'I-01',
        severity: 'blocker',
        finding: 'No API design documented',
        recommendation: 'Design and document APIs using RESTful or GraphQL standards'
      })
    }
    
    // I-02: Integration Catalogue
    if (!lowerText.includes('integration catalogue') && !lowerText.includes('api catalog')) {
      findings.push({
        domain: this.domain,
        principle_id: 'I-02',
        severity: 'high',
        finding: 'No integration catalogue documented',
        recommendation: 'Create and maintain integration catalogue with all system dependencies'
      })
    }
    
    // I-03: Integration Security
    if (!lowerText.includes('oauth') && !lowerText.includes('authentication') && !lowerText.includes('api key')) {
      findings.push({
        domain: this.domain,
        principle_id: 'I-03',
        severity: 'blocker',
        finding: 'No integration security mechanism documented',
        recommendation: 'Define authentication and authorization mechanisms for all integrations'
      })
    }
    
    return findings
  }
}
