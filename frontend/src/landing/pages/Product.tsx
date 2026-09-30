import { Page } from '../components/Chrome'
import { HowItWorks } from '../sections/HowItWorks'
import { Trust } from '../sections/Trust'

export default function Product() {
  return (
    <Page>
      <HowItWorks titleAs="h1" />
      <Trust />
    </Page>
  )
}
