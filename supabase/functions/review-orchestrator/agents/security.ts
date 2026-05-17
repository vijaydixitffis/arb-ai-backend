import { DomainAgent, Finding } from './domain-agent.ts'

export class SecurityDomainAgent extends DomainAgent {
  domain = 'security'
  relevantPrinciples = ['S-01', 'S-02', 'S-03', 'S-04', 'S-STD-01']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // S-01: Security Architecture
    if (!lowerText.includes('security architecture') && !lowerText.includes('security design')) {
      findings.push({
        domain: this.domain,
        principle_id: 'S-01',
        severity: 'blocker',
        finding: 'No security architecture documented',
        recommendation: 'Provide comprehensive security architecture with threat model'
      })
    }
    
    // S-02: Authentication & Authorization
    if (!lowerText.includes('authentication') && !lowerText.includes('authorization')) {
      findings.push({
        domain: this.domain,
        principle_id: 'S-02',
        severity: 'blocker',
        finding: 'No authentication/authorization mechanism documented',
        recommendation: 'Define authentication (MFA, SSO) and authorization (RBAC, ABAC) mechanisms'
      })
    }
    
    // S-03: Encryption
    if (!lowerText.includes('encryption') && !lowerText.includes('tls') && !lowerText.includes('ssl')) {
      findings.push({
        domain: this.domain,
        principle_id: 'S-03',
        severity: 'blocker',
        finding: 'No encryption strategy documented',
        recommendation: 'Define encryption at rest and in transit requirements'
      })
    }
    
    // S-04: Compliance
    if (!lowerText.includes('compliance') && !lowerText.includes('gdpr') && !lowerText.includes('pci')) {
      findings.push({
        domain: this.domain,
        principle_id: 'S-04',
        severity: 'high',
        finding: 'No compliance requirements documented',
        recommendation: 'Identify applicable compliance frameworks (GDPR, PCI-DSS, SOC2, etc.)'
      })
    }
    
    return findings
  }
}
