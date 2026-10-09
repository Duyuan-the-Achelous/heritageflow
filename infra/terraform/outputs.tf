output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "api_url" {
  value = "${var.certificate_arn == null ? "http" : "https"}://${aws_lb.api.dns_name}"
}

output "dynamodb_table" {
  value = aws_dynamodb_table.main.name
}

output "event_queue_url" {
  value = aws_sqs_queue.events.url
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service" {
  value = aws_ecs_service.api.name
}

