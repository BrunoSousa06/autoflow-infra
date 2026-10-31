resource "aws_route_table" "route_table" {
  vpc_id = aws_vpc.autoflow_vpc.id


  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }

}

resource "aws_route_table_association" "route_table_association" {
  count          = 3
  subnet_id      = aws_subnet.subnet_public[count.index].id
  route_table_id = aws_route_table.route_table.id
}




resource "aws_eip" "nat_eip" {
  count      = var.create_nat_gateway ? 1 : 0
  domain     = "vpc"
  depends_on = [aws_internet_gateway.igw]
  tags       = { Name = "${var.project_name}-nat-eip" }
}

resource "aws_nat_gateway" "nat" {
  count         = var.create_nat_gateway ? 1 : 0
  allocation_id = aws_eip.nat_eip[0].id
  subnet_id     = aws_subnet.subnet_public[0].id

  tags       = { Name = "${var.project_name}-nat-gateway" }
  depends_on = [aws_internet_gateway.igw]
}

resource "aws_route_table" "route_table_private" {
  vpc_id = aws_vpc.autoflow_vpc.id

  dynamic "route" {
    for_each = var.create_nat_gateway ? [1] : []

    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.nat[0].id
    }
  }

  tags = {
    Name = "${var.project_name}-private-rt"
  }
}

resource "aws_route_table_association" "private_association" {
  count          = 3
  subnet_id      = aws_subnet.subnet_private[count.index].id
  route_table_id = aws_route_table.route_table_private.id
}

moved {
  from = aws_eip.nat_eip
  to   = aws_eip.nat_eip[0]
}

moved {
  from = aws_nat_gateway.nat
  to   = aws_nat_gateway.nat[0]
}
