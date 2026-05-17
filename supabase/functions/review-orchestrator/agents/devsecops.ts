import { DomainAgent, Finding } from './domain-agent.ts'

export class DevSecOpsDomainAgent extends DomainAgent {
  domain = 'devsecops'
  relevantPrinciples = ['DS-01', 'DS-02', 'DS-03', 'DS-STD-01']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // DS-01: CI/CD Pipeline
    if (!lowerText.includes('ci/cd') && !lowerText.includes('cicd') && !lowerText.includes('pipeline')) {
      findings.push({
        domain: this.domain,
        principle_id: 'DS-01',
        severity: 'blocker',
        finding: 'No CI/CD pipeline documented',
        recommendation: 'Define CI/CD pipeline with build, test, and deployment stages'
      })
    }
    
    // DS-02: DevSecOps Practices
    if (!lowerText.includes('sast') && !lowerText.includes('dast') && !lowerText.includes('security scan')) {
      findings.push({
        domain: this.domain,
        principle_id: 'DS-02',
        severity: 'high',
        finding: 'No security scanning in CI/CD documented',
        recommendation: 'Integrate SAST, DAST, and dependency scanning into CI/CD pipeline'
      })
    }
    
    // DS-03: Quality Gates
    if (!lowerText.includes('quality gate') && !lowerText.includes('code coverage') && !lowerText.includes('test')) {
      findings.push({
        domain: this.domain,
        principle_id: 'DS-03',
        severity: 'high',
        finding: 'No quality gates defined',
        recommendation: 'Define quality gates including code coverage, test coverage, and security thresholds'
      })
    }
    
    return findings
  }
}
